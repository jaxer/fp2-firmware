#pragma once
#include "protocol.h"
#include <array>
#include <cstdint>

namespace fp2_wire {
// Optional action vocabulary only; caller supplies authorization, physical
// prerequisites and exclusive command ownership. Never starts on construction.
class Learning {
 public:
  enum class Action { NONE, BACKGROUND, AUTO_EDGE };
  enum class Status { UNKNOWN, AWAITING_COMPLETION, COMPLETED, OUTCOME_UNKNOWN };
  struct State {
    Action action{Action::NONE};
    Status status{Status::UNKNOWN};
    bool acknowledged{}, ack_failed{}, background_complete{}, candidate_available{};
    uint8_t ack_status{}, ack_sequence{};
    std::array<uint8_t, 40> candidate{};
  };
  // Only true-valued start requests. There is no cancel, apply or retry command.
  // Local timeout is caller policy, not recovered stock completion timing.
  bool start(Action action, uint8_t sequence, uint32_t now, uint32_t timeout_ms, Frame &out);
  bool observe(const Frame &frame);
  void expire(uint32_t now);
  const State &state() const { return state_; }
 private:
  State state_{};
  uint32_t started_at_{}, timeout_ms_{};
};
}  // namespace fp2_wire
