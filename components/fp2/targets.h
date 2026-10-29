#pragma once
#include "protocol.h"
#include <array>

namespace fp2_wire {
// Lossless0117 record representation. A/B are signed wire integers in
// hundredths of native coordinates; physical units/axis names are unproved.
struct Target {
  uint8_t id{};
  int16_t a_hundredths{};
  int16_t b_hundredths{};
  uint16_t field_5_6_raw{};
  uint16_t magnitude_raw{};
  uint16_t scaled_field_raw{};
  uint8_t flag_raw{};
  uint8_t r29_or_ff_raw{};
  uint8_t r30_raw{};
  std::array<uint8_t, 14> raw{};
};
struct TargetSnapshot {
  uint8_t sequence{};
  std::vector<Target> targets;
};
// Only exact0117/op5/type6 snapshots within the transport2048-byte payload
// bound. No invented target capacity or eligibility/posture filter. Empty is
// valid; malformed input leaves output unchanged. No clock, I/O or freshness.
bool decode_targets(const Frame &frame, TargetSnapshot &output);
}  // namespace fp2_wire
