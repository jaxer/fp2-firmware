#include "learning.h"
#include <algorithm>

namespace fp2_wire {
namespace {
uint16_t id_for(Learning::Action action) { return action==Learning::Action::BACKGROUND?0x0113:0x0150; }
}
bool Learning::start(Action action, uint8_t sequence, uint32_t now, uint32_t timeout_ms, Frame &out) {
  if ((action!=Action::BACKGROUND && action!=Action::AUTO_EDGE) || timeout_ms==0 ||
      state_.status==Status::AWAITING_COMPLETION || state_.status==Status::OUTCOME_UNKNOWN) return false;
  const auto id=id_for(action);
  //0113: CRC-valid retained capture sniff_data_ai_learning_process.txt:256.
  //0150: stock ESP32 adapter400e2b64, type4 at2b6f, op2 at2bdf/2be5;
  // host-dispatch-catalog entry47 binds that adapter to0150.
  out={sequence,2,{uint8_t(id>>8),uint8_t(id),4,1}};
  state_.action=action;
  state_.status=Status::AWAITING_COMPLETION;
  state_.acknowledged=false; state_.ack_failed=false; state_.ack_status=0; state_.ack_sequence=0;
  if (action==Action::BACKGROUND) state_.background_complete=false;
  else state_.candidate_available=false;
  started_at_=now; timeout_ms_=timeout_ms;
  return true;
}
void Learning::expire(uint32_t now) {
  if (state_.status==Status::AWAITING_COMPLETION && uint32_t(now-started_at_)>=timeout_ms_)
    state_.status=Status::OUTCOME_UNKNOWN; // No abort/retry: radar may still be running.
}
bool Learning::observe(const Frame &frame) {
  const auto &p=frame.payload;
  if (p.size()<2) return false;
  const uint16_t id=(uint16_t(p[0])<<8)|p[1];
  const bool outstanding=state_.status==Status::AWAITING_COMPLETION || state_.status==Status::OUTCOME_UNKNOWN;
  if (frame.operation==3 && outstanding && id==id_for(state_.action)) {
    if (p.size()!=4 || p[2]!=0) return false;
    // Retained0113 request/ACK sequences58/113 differ. Preserve the observed
    // ACK sequence; attribute association does not prove transactional causality.
    state_.ack_sequence=frame.sequence;
    state_.ack_status=p[3]; state_.acknowledged=p[3]==0; state_.ack_failed=p[3]!=0;
    if (p[3]!=0) state_.status=Status::OUTCOME_UNKNOWN;
    return true; // Receipt ACK is never completion or durable-save evidence.
  }
  if (frame.operation!=5) return false;
  if (id==0x0113) {
    if (p.size()!=4 || p[2]!=4 || p[3]!=1) return false;
    state_.background_complete=true;
    if (outstanding && state_.action==Action::BACKGROUND) state_.status=Status::COMPLETED;
    return true;
  }
  if (id==0x0149) {
    // Type6 has a BE16 nested length; a candidate is exactly40 bytes.
    if (p.size()!=45 || p[2]!=6 || p[3]!=0 || p[4]!=40) return false;
    std::copy(p.begin()+5,p.end(),state_.candidate.begin());
    state_.candidate_available=true;
    if (outstanding && state_.action==Action::AUTO_EDGE) state_.status=Status::COMPLETED;
    return true;
  }
  return false;
}
}  // namespace fp2_wire
