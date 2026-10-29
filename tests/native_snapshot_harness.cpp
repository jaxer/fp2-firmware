
#include "native_snapshot.h"
// Synthetic isolated fixtures only; no device, captured configuration or live service.
#include "monitor_protocol.h"
#include <vector>
#include <array>
const std::vector<uint8_t> prefix(fp2_wire::monitor_protocol::CODE_PREFIX.begin(),fp2_wire::monitor_protocol::CODE_PREFIX.end());
constexpr uint32_t instance=0x08001000;

constexpr uint64_t baseline=10,final_counter=12;
const std::vector<uint8_t> context={0,0,0};
const auto active=[] {std::vector<uint8_t> v(32);v[1]=1;v[4]=1;return v;}();
const auto cache=[] {std::vector<uint8_t> v(120);v[12]=5;return v;}();

#include <cassert>
#include <iostream>
using namespace fp2_wire;
uint32_t be(const uint8_t *p){return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];}
std::vector<uint8_t> little(uint64_t value,unsigned count){std::vector<uint8_t> p;for(unsigned i=0;i<count;++i)p.push_back(value>>(8*i));return p;}
Frame response(const Frame &request,std::vector<uint8_t> body) {
 auto &r=request.payload;
 Frame f{4,4,{1,2,5,0,uint8_t(8+body.size()),3,'M',0,r[7],r[8],r[9],r[10],uint8_t(body.size())}};
 f.payload.insert(f.payload.end(),body.begin(),body.end());return f;
}
struct Simulator {
 unsigned mode{},pointers{},gates{},contexts{},counters{},actives{},caches{};
 Frame reply(const Frame &request) {
  const auto &r=request.payload;
  assert(request.operation==1 && r.size()==12);
  assert(std::vector<uint8_t>(r.begin(),r.begin()+7)==std::vector<uint8_t>({1,2,'F','P','2','M',1}));
  auto address=be(r.data()+7);std::vector<uint8_t> data;
  if(address==0x38000){data=prefix;
  if(mode==1)data[0]^=1;}
  else if(address==0x080289fc){++pointers;data=little((mode==2 || (mode==13&&pointers>=3))?0x0802fff0:instance,4);}
  else if(address==instance+0x51c){++gates;data={0,0,0,0};
  if(mode==3 || (mode==14&&gates>=3))data[1]=1;}
  else if(address==0x080289ec){++contexts;data=context;
  if(mode==4 || (mode==15&&contexts>=3))data[2]=1;}
  else if(address==instance+0x590){++counters;auto value=counters==1?baseline:final_counter;
   if(mode==5)value=baseline;
  if(mode==17&&counters==2)value=baseline+1;
  if(mode==6 && counters>1)value=baseline-1;
   if(mode==7 && counters>1)value=baseline+1001;
   if(mode==16 && counters>=3)value=baseline;
   data=little(value,8);
  } else if(address==instance+0x354){++actives;data=active;
   if(mode==8&&actives==2)data[1]^=1;
  if(mode==10)data[1]=7;
  } else if(address==instance+0x3f8){++caches;data=cache;
   if(mode==9&&caches==2)data[0]^=1;
  if(mode==11)data[0]=3;
  } else assert(false);
  assert(data.size()==r[11]);auto f=response(request,data);
  if(mode==12){f.payload[7]=1;f.payload.resize(13);f.payload[12]=0;f.payload[4]=8;}
  return f;
 }
};
void drive(NativeSnapshotReader &reader,Simulator &sim,uint32_t &now) {
 for(unsigned steps=0;steps<1000 && !reader.complete() && !reader.failed();++steps){
  Frame request;
  if(reader.next_request(now,19,request)){
   Frame again;assert(!reader.next_request(now,20,again)); // One pending read.
   auto reply=sim.reply(request);
   assert(reader.ingest(reply,now));
  }
  now+=10;
 }
}
int main(){
 NativeSnapshotReader idle;Frame untouched{7,7,{7}};assert(!idle.next_request(0,0,untouched));
 for(unsigned mode=0;mode<=17;++mode){
  NativeSnapshotReader reader;Simulator sim;sim.mode=mode;uint32_t now=0;reader.invalidate(now);drive(reader,sim,now);
  if(mode==0 || mode==10 || mode==11 || mode==17){
   assert(reader.complete()&&!reader.failed());const auto &s=reader.snapshot();
   assert(s.counter_final-s.counter_baseline>=2 && s.counter_final-s.counter_baseline<=1000);
   assert(s.requests==(mode==17?21:17) && s.instance==instance); // No full settings/map reads.
   assert(s.zones[3].known && s.zones[3].occupied); // Synthetic occupied zone4 fixture.
   if(mode==10 || mode==11)assert(!s.zones[0].known);
   else assert(s.zones[0].known && !s.zones[0].occupied);
   assert(!s.zones[29].known && !s.zones[29].configured);
   auto requests=s.requests;assert(!reader.next_request(now,20,untouched));assert(s.requests==requests);
  } else {assert(reader.failed()&&!reader.complete());assert(!reader.next_request(now,20,untouched));}
 }
 // Exact length/status checks, out-of-order address and unrelated operation.
 for(unsigned fault=0;fault<4;++fault){
  NativeSnapshotReader reader;reader.invalidate(0);Frame req;assert(reader.next_request(0,1,req));
  auto reply=response(req,prefix);
  auto unrelated=reply;unrelated.payload[11]^=1;assert(!reader.ingest(unrelated,1));
  unrelated=reply;unrelated.operation=5;assert(!reader.ingest(unrelated,1));
  if(fault==0)reply.payload[4]^=1;
  if(fault==1)reply.payload[12]--;
  if(fault==2)reply.payload.push_back(0);
  if(fault==3)reply.payload[7]=1;
  assert(reader.ingest(reply,2) && reader.failed());
  reader.invalidate(3);assert(reader.next_request(3,2,req)); // Explicit new epoch only.
 }
 NativeSnapshotReader timeout;timeout.invalidate(UINT32_MAX-200);Frame request;
 assert(timeout.next_request(UINT32_MAX-200,1,request));
 assert(!timeout.next_request(298,2,request)&&!timeout.failed());
 assert(!timeout.next_request(299,2,request)&&timeout.failed()); //500ms across rollover.
 std::cout<<"native snapshot checks passed\n";
}
