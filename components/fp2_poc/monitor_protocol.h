#pragma once
#include "protocol.h"
#include <algorithm>
#include <array>

namespace fp2_wire::monitor_protocol {
constexpr uint32_t INSTANCE_POINTER=0x080289fc, CODE_ADDRESS=0x38000;
// export.bin SHA2562df647621c86d60514df4c905ca6c8bf05b7140da50aa971305b0700e3ebcc40.
constexpr std::array<uint8_t,16> CODE_PREFIX{{0xdf,0xf8,0xbc,0xf2,0xf8,0xb5,0xaa,0xb0,
                                           0x24,0x90,0x25,0x91,0x17,0x46,0x06,0x2a}};
inline uint32_t le32(const uint8_t *p) {
  return uint32_t(p[0])|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;
}
inline uint32_t be32(const uint8_t *p) {
  return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|uint32_t(p[3]);
}
inline bool tcmb_object(uint32_t address,uint32_t size) {
  return address%4==0 && address>=0x08000000 && address<=0x08030000 && size<=0x08030000-address;
}
inline Frame read_request(uint8_t sequence,uint32_t address,uint8_t count) {
  return {sequence,1,{1,2,'F','P','2','M',1,uint8_t(address>>24),uint8_t(address>>16),
                      uint8_t(address>>8),uint8_t(address),count}};
}
enum class Reply { UNRELATED, VALID, INVALID };
// Caller supplies CRC-validated Frame. Monitor reply sequence is not an echo;
// exact address/count/tag/nested length correlate a single pending read.
inline Reply read_reply(const Frame &frame,uint32_t address,uint8_t count,const uint8_t *&data) {
  const auto &p=frame.payload;
  if(frame.operation!=4 || p.size()<13 || p[0]!=1 || p[1]!=2 || p[2]!=5 ||
     p[5]!=3 || p[6]!='M' || be32(p.data()+8)!=address) return Reply::UNRELATED;
  const size_t nested=(size_t(p[3])<<8)|p[4];
  if(nested!=p.size()-5 || p.size()!=size_t(13+p[12]) || p[7]!=0 || p[12]!=count)
    return Reply::INVALID;
  data=p.data()+13;
  return Reply::VALID;
}
inline bool code_matches(const uint8_t *data) { return std::equal(CODE_PREFIX.begin(),CODE_PREFIX.end(),data); }
}  // namespace fp2_wire::monitor_protocol
