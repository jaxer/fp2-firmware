#pragma once
#include <array>
#include <cstdint>

namespace fp2_wire {
class Orientation {
 public:
  // Already decoded signed12-bit XYZ samples; no I/O or clock access.
  // Invalid range/zero vector clears readiness and returns false.
  bool update(const std::array<std::array<int16_t, 3>, 10> &raw,
              const std::array<int16_t, 3> &correction, uint32_t now_ms);
  bool angle_ready() const { return angle_ready_; }
  bool orientation_ready() const { return orientation_ready_; }
  uint16_t tilt() const { return tilt_; }
  uint8_t direction() const { return direction_; }
  uint32_t last_update_ms() const { return last_update_ms_; }
  void invalidate();
 private:
  void accept(uint8_t candidate);
  bool angle_ready_{};
  bool orientation_ready_{};
  uint16_t tilt_{};
  uint8_t direction_{8};  // Not meaningful until orientation_ready().
  uint16_t invalid_count_{};
  uint16_t departure_36_{};
  uint16_t departure_47_{};
  uint16_t departure_5_{};
  uint32_t last_update_ms_{};
};
}  // namespace fp2_wire
