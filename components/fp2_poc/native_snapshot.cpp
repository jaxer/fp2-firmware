#include "native_snapshot.h"
#include "monitor_protocol.h"
#include <algorithm>

namespace fp2_wire {
namespace {
constexpr uint32_t POINTER = 0x080289fc, GLOBAL = 0x080289ec;
using monitor_protocol::le32;
uint64_t le64(const uint8_t *p) { return uint64_t(le32(p)) | uint64_t(le32(p+4))<<32; }
}
void NativeSnapshotReader::invalidate(uint32_t now) {
  *this = NativeSnapshotReader{};
  phase_ = Phase::PREFIX;
  snapshot_.started_at = now;
}
void NativeSnapshotReader::fail_() {
  phase_ = Phase::ERROR;
  pending_ = false;
  for (auto &zone : snapshot_.zones) zone.known = false;
}
bool NativeSnapshotReader::expired_(uint32_t now) {
  if (phase_ == Phase::DONE || phase_ == Phase::ERROR) return true;
  if ((pending_ && uint32_t(now-pending_at_) >= 500) ||
      (progress_started_ && uint32_t(now-progress_at_) >= 3000)) {
    fail_();
    return true;
  }
  return false;
}
bool NativeSnapshotReader::progress_(uint64_t value) {
  if (value < previous_counter_ || value < snapshot_.counter_baseline ||
      value-snapshot_.counter_baseline > 1000) {
    fail_();
    return false;
  }
  previous_counter_ = value;
  return true;
}
bool NativeSnapshotReader::next_request(uint32_t now, uint8_t sequence, Frame &out) {
  if (expired_(now) || pending_) return false;
  uint32_t address = 0;
  uint8_t count = 0;
  const auto instance = snapshot_.instance;
  switch (phase_) {
    case Phase::PREFIX: address=0x38000; count=16; break;
    case Phase::POINTER: case Phase::POLL_POINTER: case Phase::FINAL_POINTER:
      if (phase_ == Phase::POLL_POINTER && poll_wait_ && uint32_t(now-poll_at_) < 100) return false;
      poll_wait_=false; address=POINTER; count=4; break;
    case Phase::GATE: case Phase::POLL_GATE: case Phase::FINAL_GATE:
      address=instance+0x51c; count=4; break;
    case Phase::CONTEXT: case Phase::POLL_CONTEXT: case Phase::FINAL_CONTEXT:
      address=GLOBAL; count=3; break;
    case Phase::BASELINE: case Phase::POLL_COUNTER: case Phase::FINAL_COUNTER:
      address=instance+0x590; count=8; break;
    case Phase::ACTIVE: case Phase::ACTIVE_AGAIN: address=instance+0x354; count=32; break;
    case Phase::CACHE: case Phase::CACHE_AGAIN: address=instance+0x3f8; count=120; break;
    default: return false;
  }
  out = monitor_protocol::read_request(sequence,address,count);
  pending_=true; pending_address_=address; pending_count_=count; pending_at_=now;
  ++snapshot_.requests;
  return true;
}
bool NativeSnapshotReader::ingest(const Frame &frame, uint32_t now) {
  if (expired_(now) || !pending_ || frame.operation != 4) return false;
  const uint8_t *data=nullptr;
  const auto reply=monitor_protocol::read_reply(frame,pending_address_,pending_count_,data);
  if (reply==monitor_protocol::Reply::UNRELATED) return false;
  if (reply==monitor_protocol::Reply::INVALID) { fail_(); return true; }
  pending_=false;
  switch (phase_) {
    case Phase::PREFIX:
      if (!monitor_protocol::code_matches(data)) { fail_(); break; }
      phase_=Phase::POINTER; break;
    case Phase::POINTER:
      snapshot_.instance=le32(data);
      if (snapshot_.instance%4 || snapshot_.instance<0x08000000 || snapshot_.instance>0x08030000-3000) {
        fail_(); break;
      }
      phase_=Phase::GATE; break;
    case Phase::GATE: case Phase::POLL_GATE: case Phase::FINAL_GATE:
      if (data[1]!=0) { fail_(); break; }
      phase_=phase_==Phase::GATE?Phase::CONTEXT:
             phase_==Phase::POLL_GATE?Phase::POLL_CONTEXT:Phase::FINAL_CONTEXT; break;
    case Phase::CONTEXT:
      std::copy(data,data+3,context_.begin());
      if (data[2]!=0) { fail_(); break; }
      phase_=Phase::BASELINE; break;
    case Phase::BASELINE:
      previous_counter_=snapshot_.counter_baseline=le64(data);
      progress_started_=true; progress_at_=now;
      phase_=Phase::POLL_POINTER; break;
    case Phase::POLL_POINTER: case Phase::FINAL_POINTER:
      if (le32(data)!=snapshot_.instance) { fail_(); break; }
      phase_=phase_==Phase::POLL_POINTER?Phase::POLL_GATE:Phase::FINAL_GATE; break;
    case Phase::POLL_CONTEXT: case Phase::FINAL_CONTEXT:
      if (!std::equal(context_.begin(),context_.end(),data)) { fail_(); break; }
      phase_=phase_==Phase::POLL_CONTEXT?Phase::POLL_COUNTER:Phase::FINAL_COUNTER; break;
    case Phase::POLL_COUNTER: {
      const auto value=le64(data);
      if (!progress_(value)) break;
      if (value-snapshot_.counter_baseline>=2) phase_=Phase::ACTIVE;
      else { phase_=Phase::POLL_POINTER; poll_wait_=true; poll_at_=now; }
      break;
    }
    case Phase::ACTIVE: std::copy(data,data+32,active_.begin()); phase_=Phase::CACHE; break;
    case Phase::CACHE: std::copy(data,data+120,cache_.begin()); phase_=Phase::ACTIVE_AGAIN; break;
    case Phase::ACTIVE_AGAIN:
      if (!std::equal(active_.begin(),active_.end(),data)) { fail_(); break; }
      phase_=Phase::CACHE_AGAIN; break;
    case Phase::CACHE_AGAIN:
      if (!std::equal(cache_.begin(),cache_.end(),data)) { fail_(); break; }
      phase_=Phase::FINAL_POINTER; break;
    case Phase::FINAL_COUNTER: {
      const auto value=le64(data);
      if (!progress_(value)) break;
      snapshot_.counter_final=value; snapshot_.completed_at=now;
      for (size_t index=0;index<30;++index) {
        auto &zone=snapshot_.zones[index];
        zone.active_byte=active_[index+1]; zone.cached_word=le32(cache_.data()+index*4);
        zone.configured=zone.active_byte==1;
        zone.known=zone.configured && (zone.cached_word==0 || zone.cached_word==5);
        zone.occupied=zone.known && zone.cached_word==5;
      }
      phase_=Phase::DONE; break;
    }
    default: fail_(); break;
  }
  return true;
}
}  // namespace fp2_wire
