#pragma once
#include "protocol.h"
#include "native_snapshot.h"
#include <array>
#include <cstdint>

namespace fp2_wire {
struct OccupancyState {
  bool known{false};
  // Meaningful only when known. Invalidation preserves the last observation.
  bool occupied{false};
  uint32_t updated_ms{0};
};

// Pure observation model. Caller supplies monotonic modulo-2^32 milliseconds.
// timeout=0 disables expiry; silence never produces a known vacant state.
class Occupancy {
 public:
  explicit Occupancy(uint32_t timeout_ms = 0) : timeout_ms_(timeout_ms) {}
  // True only for an accepted authoritative op4/op5 report, including repeats.
  bool ingest(const ::fp2_wire::Frame &frame, uint32_t now_ms);
  // True if at least one known observation expires at elapsed >= timeout.
  bool tick(uint32_t now_ms);
  void invalidate();
  // Configuration changes invalidate observations, never infer vacancy. The
  // room and other zones retain their actual report provenance.
  void invalidate_zone(uint32_t id);
  void invalidate_zones();
  // Seed unknown zones only from the reader's guarded real RAM result. Never
  // construct0142 events or overwrite known UART observations; no room change.
  void seed_native_cache(const NativeSnapshot &snapshot, uint32_t now_ms);
  const OccupancyState &room() const { return room_; }
  // Stable IDs1..30; invalid IDs return an always-unknown sentinel.
  const OccupancyState &zone(uint8_t id) const;
 private:
  uint32_t timeout_ms_;
  OccupancyState room_;
  std::array<OccupancyState, 30> zones_{};
  const OccupancyState invalid_{};
};
}  // namespace fp2_wire
