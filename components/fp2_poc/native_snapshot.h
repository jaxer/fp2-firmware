#pragma once
#include "protocol.h"
#include <array>
#include <cstdint>

namespace fp2_wire {
struct NativeZoneState {
  bool known{}, occupied{}, configured{};
  uint8_t active_byte{};
  uint32_t cached_word{};
};
struct NativeSnapshot {
  std::array<NativeZoneState, 30> zones{};
  uint32_t instance{}, started_at{}, completed_at{}, requests{};
  uint64_t counter_baseline{}, counter_final{};
};
// One-shot, read-only bootstrap. Caller owns configuration/reset exclusion and
// must invalidate on any epoch change. Results are native RAM observations,
// never synthetic0142 events or an atomic snapshot. Frame CRC belongs to Parser.
class NativeSnapshotReader {
 public:
  void invalidate(uint32_t now);
  bool next_request(uint32_t now, uint8_t sequence, Frame &out);
  bool ingest(const Frame &frame, uint32_t now);
  bool complete() const { return phase_ == Phase::DONE; }
  bool failed() const { return phase_ == Phase::ERROR; }
  const NativeSnapshot &snapshot() const { return snapshot_; }
 private:
  enum class Phase { PREFIX, POINTER, GATE, CONTEXT, BASELINE,
    POLL_POINTER, POLL_GATE, POLL_CONTEXT, POLL_COUNTER,
    ACTIVE, CACHE, ACTIVE_AGAIN, CACHE_AGAIN,
    FINAL_POINTER, FINAL_GATE, FINAL_CONTEXT, FINAL_COUNTER, DONE, ERROR };
  bool expired_(uint32_t now);
  bool progress_(uint64_t value);
  void fail_();
  Phase phase_{Phase::ERROR};
  NativeSnapshot snapshot_{};
  std::array<uint8_t, 3> context_{};
  std::array<uint8_t, 32> active_{};
  std::array<uint8_t, 120> cache_{};
  uint64_t previous_counter_{};
  uint32_t pending_address_{}, pending_at_{}, progress_at_{}, poll_at_{};
  uint8_t pending_count_{};
  bool pending_{}, progress_started_{}, poll_wait_{};
};
}  // namespace fp2_wire
