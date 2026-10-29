
#include "normal_commands.h"
#include <cassert>
#include <limits>
using fp2_wire::Frame;
using namespace fp2_commands;
static const Frame sentinel{91, 5, {9,8,7}};
bool unchanged(const Frame& f) {
 return f.sequence==sentinel.sequence && f.operation==sentinel.operation && f.payload==sentinel.payload;
}
void same(const Frame& f, unsigned seq, std::initializer_list<uint8_t> body) {
 assert(f.sequence==seq && f.operation==2 && f.payload==std::vector<uint8_t>(body));
}
int main() {
 Frame f=sentinel; uint8_t map[40]{};
 std::vector<uint8_t> decoded={9,8,7};
 for(size_t n:{0u,1u,79u,81u,160u}) {
  assert(!decode_mask_hex(std::string(n,'0'),decoded));assert(decoded==std::vector<uint8_t>({9,8,7}));
 }
 for(size_t index=0;index<80;++index) {
  for(unsigned byte=0;byte<=255;++byte) {
   const bool hex=(byte>='0'&&byte<='9')||(byte>='a'&&byte<='f')||(byte>='A'&&byte<='F');
   if (hex) {
    continue;
   }
   std::string text(80, '0');
   text[index] = char(byte);
   assert(!decode_mask_hex(text,decoded));assert(decoded==std::vector<uint8_t>({9,8,7}));
  }
 }
 assert(decode_mask_hex(std::string(80,'0'),decoded));assert(decoded==std::vector<uint8_t>(40,0));
 assert(decode_mask_hex(std::string(80,'F'),decoded));assert(decoded==std::vector<uint8_t>(40,255));
 assert(decode_mask_hex(std::string(80,'a'),decoded));assert(decoded==std::vector<uint8_t>(40,170));
 // Every16-bit ID, including all forbidden reset/update/mode identifiers.
 for (uint32_t id=0;id<=65536;++id) {
  f=sentinel;bool scalar=id==0x106||id==0x111||id==0x122||id==0x170;
  assert(scalar_control(0,id,0,f)==scalar);if(!scalar)assert(unchanged(f));
  f=sentinel;bool property=id==0x151||id==0x152||id==0x153;
  assert(zone_property(0,id,1,1,f)==property);if(!property)assert(unchanged(f));
  f=sentinel;bool special=id==0x107||id==0x109||id==0x110;
  assert(special_map(0,id,map,40,f)==special);if(!special)assert(unchanged(f));
 }
 for(uint32_t n=0;n<=65536;++n) {
  f=sentinel;bool zone=n>=1&&n<=30;
  assert(zone_geometry(0,n,map,40,f)==zone);if(!zone)assert(unchanged(f));
  for(uint32_t id: {0x151u,0x152u,0x153u}) {
   f=sentinel;assert(zone_property(0,id,n,1,f)==zone);if(!zone)assert(unchanged(f));
   f=sentinel;bool value=id==0x151?(n>=1&&n<=3):id==0x152?n<=39:n<=1;
   assert(zone_property(0,id,1,n,f)==value);if(!value)assert(unchanged(f));
  }
  for(uint32_t id: {0x106u,0x111u,0x122u,0x170u}) {
   f=sentinel;bool valid=n<=((id==0x106||id==0x122)?2u:3u);
   assert(scalar_control(0,id,n,f)==valid);if(!valid)assert(unchanged(f));
  }
 }
 for(uint32_t n: {256u,65536u,0xffffffffu}) {
  f=sentinel;assert(!scalar_control(n,0x106,0,f)&&unchanged(f));
  assert(!zone_property(n,0x151,1,1,f)&&unchanged(f));
  assert(!zone_geometry(n,1,map,40,f)&&unchanged(f));
  assert(!special_map(n,0x107,map,40,f)&&unchanged(f));
  assert(!scalar_control(0,0x106,n,f)&&unchanged(f));
  assert(!zone_property(0,0x152,1,n,f)&&unchanged(f));
  assert(!zone_geometry(0,n,map,40,f)&&unchanged(f));
  assert(!special_map(0,n,map,40,f)&&unchanged(f));
  assert(!scalar_control(0,n,0,f)&&unchanged(f));
  assert(!zone_property(0,n,1,1,f)&&unchanged(f));
  assert(!zone_property(0,0x151,n,1,f)&&unchanged(f));
 }
 for(size_t length: {0u,1u,39u,41u,255u,65536u}) {
  f=sentinel;assert(!zone_geometry(0,1,map,length,f)&&unchanged(f));
  assert(!special_map(0,0x107,map,length,f)&&unchanged(f));
 }
 f=sentinel;assert(!zone_geometry(0,1,nullptr,40,f)&&unchanged(f));
 assert(!special_map(0,0x107,nullptr,40,f)&&unchanged(f));
 assert(zone_geometry(255,30,map,40,f)); // All-zero map deletes exactly this zone.
 assert(f.sequence==255&&f.payload.size()==46&&f.payload[5]==30);
 for(size_t i=6;i<f.payload.size();++i)assert(f.payload[i]==0);
 assert(zone_property(255,0x151,30,2,f));same(f,255,{1,81,1,30,2});

}
