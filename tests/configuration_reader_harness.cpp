
#include "configuration_reader.h"
#include "monitor_protocol.h"
// Synthetic isolated fixtures only; no device, captured configuration or live service.
#include "monitor_protocol.h"
#include <vector>
#include <array>
const std::vector<uint8_t> prefix(fp2_wire::monitor_protocol::CODE_PREFIX.begin(),fp2_wire::monitor_protocol::CODE_PREFIX.end());
constexpr uint32_t instance=0x08001000;

constexpr uint32_t masks_pointer=0x08010000;
const auto zone_masks=[] { std::array<std::vector<uint8_t>,30> result; for(unsigned i=0;i<30;++i){result[i].resize(40);result[i][i%40]=uint8_t(i+1);} return result;}();
const auto zone_flags=[] {std::array<std::array<uint8_t,4>,30> result{};for(unsigned i=0;i<30;++i)result[i]={1,uint8_t(i%4),uint8_t(i+2),uint8_t(i%2)};return result;}();
const uint32_t scalar_values[]={2,3,0,1};
const std::vector<uint8_t> special_masks[]={std::vector<uint8_t>(40,0x55),std::vector<uint8_t>(40,0xaa),std::vector<uint8_t>(40,0)};

#include <cassert>
#include <iostream>
#include <map>
using namespace fp2_wire;
std::vector<uint8_t> le(uint32_t v){return {uint8_t(v),uint8_t(v>>8),uint8_t(v>>16),uint8_t(v>>24)};}
Frame reply(const Frame&r,std::vector<uint8_t> body){const auto&p=r.payload;
 Frame f{4,4,{1,2,5,0,uint8_t(8+body.size()),3,'M',0,p[7],p[8],p[9],p[10],uint8_t(body.size())}};
 f.payload.insert(f.payload.end(),body.begin(),body.end());return f;
}
struct Sim {
 std::map<uint32_t,std::vector<uint8_t>> memory;
 std::map<uint32_t,unsigned> counts;
 unsigned fault{};uint32_t pointer_field{},mask_address{},metadata_address{};
 Sim(){memory[0x38000]=prefix;memory[0x080289fc]=le(instance);}
 void zone(unsigned id){
  pointer_field=instance+0x13c+4*id;mask_address=masks_pointer+40*id;metadata_address=instance+0x354+id;
  memory[pointer_field]=le(mask_address);memory[mask_address]=zone_masks[id-1];
  memory[metadata_address]={zone_flags[id-1][0]};memory[instance+0x5bc+id]={zone_flags[id-1][1]};
  memory[instance+0xae1+id]={zone_flags[id-1][2]};memory[instance+0xb01+id]={zone_flags[id-1][3]};
 }
 void scalar(unsigned index){const uint32_t offsets[]={0xa4,0xb4,0x510,0xb9c};metadata_address=instance+offsets[index];
  memory[metadata_address]=le(scalar_values[index]);}
 void special(unsigned index){const uint32_t offsets[]={0xa8,0xac,0xb0};
  pointer_field=instance+offsets[index];mask_address=0x08010000+40*index; // Isolated TCMB allocation fixture.
  memory[pointer_field]=le(mask_address);memory[mask_address]=special_masks[index];}
 Frame respond(const Frame&r){
  assert(r.operation==1&&r.payload.size()==12);
  assert(std::vector<uint8_t>(r.payload.begin(),r.payload.begin()+7)==std::vector<uint8_t>({1,2,'F','P','2','M',1}));
  const auto address=monitor_protocol::be32(r.payload.data()+7);unsigned count=++counts[address];
  assert(memory.count(address));auto data=memory.at(address);assert(data.size()==r.payload[11]);
  if(fault==1&&address==0x38000)data[0]^=1;
  if(fault==2&&address==0x080289fc)data=le(0x0802fff0);
  if(fault==3&&address==pointer_field)data=le(0x0802fff0);
  if(fault==4&&address==mask_address&&count==2)data[0]^=1;
  if(fault==5&&address==metadata_address&&count==2)data[0]^=1;
  if(fault==12&&address==metadata_address&&count==2)data[3]^=1;
  if(fault==6&&address==0x080289fc&&count==2)data=le(instance+4);
  if(fault==7&&address==0x080289fc&&count==3)data=le(instance+4);
  if(fault==8&&address==pointer_field&&count==2)data=le(mask_address+4);
  if(fault==9&&address==pointer_field)data=le(mask_address+1);
  auto f=reply(r,data);
  if(fault==10)f.payload[7]=1;
  if(fault==11)f.payload[4]^=1;
  return f;
 }
};
void drive(ConfigurationReader&r,Sim&s,uint32_t now=0,unsigned delay=10){
 for(unsigned i=0;i<100&&!r.complete()&&!r.failed();++i){Frame request;
  if(r.next_request(now,17,request)){
   Frame unused{7,7,{7}};assert(!r.next_request(now,18,unused)&&unused.operation==7);
   auto f=s.respond(request);now+=delay;r.ingest(f,now);
  }else now+=10;
 }
}
int main(){
 for(unsigned id=1;id<=30;++id){ConfigurationReader r;Sim s;s.zone(id);assert(r.start_zone(id,0));drive(r,s);
  assert(r.complete());auto &v=r.result();assert(v.zone_id==id&&v.requests==16&&v.instance==instance);
  assert(v.active_byte==zone_flags[id-1][0]&&v.sensitivity==zone_flags[id-1][1]);
  assert(v.type==zone_flags[id-1][2]&&v.close_away==zone_flags[id-1][3]);
  assert(std::vector<uint8_t>(v.mask.begin(),v.mask.end())==zone_masks[id-1]);
  Frame extra;assert(!r.next_request(1000,5,extra));
 }
 const uint32_t attrs[]={0x0106,0x0111,0x0122,0x0170};
 for(unsigned i=0;i<4;++i){ConfigurationReader r;Sim s;s.scalar(i);assert(r.start_scalar(attrs[i],0));drive(r,s);
  assert(r.complete()&&r.result().raw_value==scalar_values[i]&&r.result().requests==6);
  assert(r.result().wire_value==(i==0?int64_t(3)-scalar_values[i]:scalar_values[i]));
 }
 // All native scalar fields are32-bit words, including unsupported upper bits.
 for(unsigned i=0;i<4;++i){
  const uint32_t offsets[]={0xa4,0xb4,0x510,0xb9c};
  ConfigurationReader r;Sim s;s.scalar(i);s.memory[instance+offsets[i]]=le(0x01000003);
  assert(r.start_scalar(attrs[i],0));drive(r,s);assert(r.complete());
  assert(r.result().raw_value==0x01000003);
  assert(r.result().wire_value==(i==0?int64_t(3)-0x01000003:0x01000003));
  ConfigurationReader changing;Sim changed;changed.scalar(i);changed.fault=12;
  assert(changing.start_scalar(attrs[i],0));drive(changing,changed);assert(changing.failed());
 }
 for(unsigned i=0;i<3;++i){const uint32_t attrs[]={0x0107,0x0109,0x0110};
  ConfigurationReader r;Sim s;s.special(i);assert(r.start_special_map(attrs[i],0));drive(r,s);
  assert(r.complete()&&r.result().requests==8);
  assert(std::vector<uint8_t>(r.result().mask.begin(),r.result().mask.end())==special_masks[i]);
 }
 for(unsigned fault=1;fault<=11;++fault){ConfigurationReader r;Sim s;s.zone(4);s.fault=fault;
  assert(r.start_zone(4,0));drive(r,s);assert(r.failed()&&!r.complete());}
 // All raw scalar values survive losslessly, even outside known input enums.
 ConfigurationReader inverse;Sim iv;iv.scalar(0);iv.memory[instance+0xa4]=le(UINT32_MAX);
 assert(inverse.start_scalar(0x0106,0));drive(inverse,iv);assert(inverse.complete());
 assert(inverse.result().wire_value==int64_t(3)-UINT32_MAX);
 ConfigurationReader invalid;assert(!invalid.start_zone(0,0)&&!invalid.start_zone(31,0));
 assert(!invalid.start_zone(257,0)&&!invalid.start_zone(UINT32_MAX,0));
 assert(!invalid.start_scalar(0x10106,0)&&!invalid.start_special_map(0x10107,0));
 assert(!invalid.start_scalar(0x0116,0)&&!invalid.start_special_map(0x0114,0));
 assert(invalid.start_zone(1,0));assert(!invalid.start_scalar(0x0106,0));
 Frame request;assert(invalid.next_request(0,1,request));auto f=reply(request,prefix);
 auto unrelated=f;unrelated.payload[11]^=1;assert(!invalid.ingest(unrelated,1));
 assert(invalid.ingest(f,2));
 // Pending timeout through clock wrap; total deadline independently bounds work.
 ConfigurationReader timeout;assert(timeout.start_zone(1,UINT32_MAX-200));
 assert(timeout.next_request(UINT32_MAX-200,1,request));
 assert(!timeout.next_request(298,2,request)&&!timeout.failed());
 assert(!timeout.next_request(299,2,request)&&timeout.failed());
 ConfigurationReader total;Sim slow;slow.zone(4);assert(total.start_zone(4,0));drive(total,slow,0,400);
 assert(total.failed());
 std::cout<<"configuration reader checks passed\n";
}
