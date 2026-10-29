#include "configuration_reader.h"
#include "monitor_protocol.h"
#include <algorithm>

namespace fp2_wire {
namespace {
uint32_t scalar_offset(uint16_t id) {
  switch(id){case 0x0106:return 0xa4;case 0x0111:return 0xb4;case 0x0122:return 0x510;case 0x0170:return 0xb9c;default:return 0;}
}
uint32_t special_offset(uint16_t id) {
  switch(id){case 0x0107:return 0xa8;case 0x0109:return 0xac;case 0x0110:return 0xb0;default:return 0;}
}
}
bool ConfigurationReader::begin_(Kind kind,uint16_t attribute,uint8_t zone_id,uint32_t now) {
  if(phase_!=Phase::DONE && phase_!=Phase::ERROR) return false;
  *this=ConfigurationReader{};
  phase_=Phase::PREFIX;result_.kind=kind;result_.attribute=attribute;
  result_.zone_id=zone_id;result_.started_at=now;
  return true;
}
bool ConfigurationReader::start_zone(uint32_t id,uint32_t now) {
  return id>=1 && id<=30 && begin_(Kind::ZONE,0x0114,static_cast<uint8_t>(id),now);
}
bool ConfigurationReader::start_scalar(uint32_t id,uint32_t now) {
  return id<=0xffff && scalar_offset(id)!=0 && begin_(Kind::SCALAR,static_cast<uint16_t>(id),0,now);
}
bool ConfigurationReader::start_special_map(uint32_t id,uint32_t now) {
  return id<=0xffff && special_offset(id)!=0 && begin_(Kind::SPECIAL_MAP,static_cast<uint16_t>(id),0,now);
}
void ConfigurationReader::fail_(){phase_=Phase::ERROR;pending_=false;}
bool ConfigurationReader::expired_(uint32_t now) {
  if(phase_==Phase::DONE || phase_==Phase::ERROR)return true;
  if(uint32_t(now-result_.started_at)>=5000 || (pending_ && uint32_t(now-pending_at_)>=500)) {
    fail_();return true;
  }
  return false;
}
uint8_t ConfigurationReader::fields_() const {
  return result_.kind==Kind::ZONE?6:result_.kind==Kind::SPECIAL_MAP?2:1;
}
bool ConfigurationReader::next_request(uint32_t now,uint8_t sequence,Frame &out) {
  if(expired_(now)||pending_)return false;
  uint32_t address=0;uint8_t count=0;
  if(phase_==Phase::PREFIX){address=monitor_protocol::CODE_ADDRESS;count=16;}
  else if(phase_==Phase::INSTANCE || phase_==Phase::MIDDLE_INSTANCE || phase_==Phase::FINAL_INSTANCE) {
    address=monitor_protocol::INSTANCE_POINTER;count=4;
  } else if(result_.kind==Kind::SCALAR) {
    address=result_.instance+scalar_offset(result_.attribute);count=4;
  } else if(result_.kind==Kind::SPECIAL_MAP) {
    address=field_==0?result_.instance+special_offset(result_.attribute):result_.map_pointer;
    count=field_==0?4:40;
  } else {
    const uint32_t offsets[]={uint32_t(0x13c+4*result_.zone_id),uint32_t(0x354+result_.zone_id),
      uint32_t(0x5bc+result_.zone_id),uint32_t(0xae1+result_.zone_id),uint32_t(0xb01+result_.zone_id)};
    address=field_==5?result_.map_pointer:result_.instance+offsets[field_];
    count=field_==0?4:field_==5?40:1;
  }
  out=monitor_protocol::read_request(sequence,address,count);
  pending_=true;pending_address_=address;pending_count_=count;pending_at_=now;
  ++result_.requests;return true;
}
void ConfigurationReader::finish_(uint32_t now) {
  if(result_.kind==Kind::SCALAR) {
    result_.raw_value=monitor_protocol::le32(first_[0].data());
    result_.wire_value=result_.attribute==0x0106?int64_t(3)-result_.raw_value:result_.raw_value;
  } else {
    const auto index=result_.kind==Kind::ZONE?5:1;
    std::copy(first_[index].begin(),first_[index].end(),result_.mask.begin());
    if(result_.kind==Kind::ZONE) {
      result_.active_byte=first_[1][0];result_.sensitivity=first_[2][0];
      result_.type=first_[3][0];result_.close_away=first_[4][0];
    }
  }
  result_.completed_at=now;phase_=Phase::DONE;
}
bool ConfigurationReader::ingest(const Frame &frame,uint32_t now) {
  if(expired_(now)||!pending_)return false;
  const uint8_t *data=nullptr;
  const auto reply=monitor_protocol::read_reply(frame,pending_address_,pending_count_,data);
  if(reply==monitor_protocol::Reply::UNRELATED)return false;
  if(reply==monitor_protocol::Reply::INVALID){fail_();return true;}
  pending_=false;
  switch(phase_) {
    case Phase::PREFIX:
      if(!monitor_protocol::code_matches(data)){fail_();break;}
      phase_=Phase::INSTANCE;break;
    case Phase::INSTANCE:
      result_.instance=monitor_protocol::le32(data);
      if(!monitor_protocol::tcmb_object(result_.instance,3000)){fail_();break;}
      phase_=Phase::FIRST;break;
    case Phase::MIDDLE_INSTANCE:case Phase::FINAL_INSTANCE:
      if(monitor_protocol::le32(data)!=result_.instance){fail_();break;}
      if(phase_==Phase::FINAL_INSTANCE)finish_(now);
      else {field_=0;phase_=Phase::SECOND;}
      break;
    case Phase::FIRST:case Phase::SECOND: {
      if(phase_==Phase::SECOND &&
         !std::equal(first_[field_].begin(),first_[field_].end(),data)){fail_();break;}
      if(phase_==Phase::FIRST) {
        first_[field_].assign(data,data+pending_count_);
        if(field_==0 && result_.kind!=Kind::SCALAR) {
          result_.map_pointer=monitor_protocol::le32(data);
          if(!monitor_protocol::tcmb_object(result_.map_pointer,40)){fail_();break;}
        }
      }
      if(++field_==fields_())phase_=phase_==Phase::FIRST?Phase::MIDDLE_INSTANCE:Phase::FINAL_INSTANCE;
      break;
    }
    default:fail_();break;
  }
  return true;
}
}  // namespace fp2_wire
