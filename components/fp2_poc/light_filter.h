#pragma once
#include "factory_calibration.h"
#include <array>
#include <cstdint>

namespace fp2_wire {
// Pure stock arithmetic with safe startup: discard10, fill10, first output20.
// Caller supplies only successful sensor reads; no clock, I/O or calibration writes.
class LightFilter {
 public:
  explicit LightFilter(const LightCalibration &calibration = {}) : calibration_(calibration) {}
  bool update(uint16_t word);
  uint32_t lux() const { return lux_; }
  static uint32_t decode(uint16_t word);
 private:
  uint32_t correct(uint32_t reading) const;
  LightCalibration calibration_{};
  std::array<uint32_t, 10> samples_{};
  uint8_t discarded_{}, filled_{}, next_{};
  uint32_t lux_{};
};
}  // namespace fp2_wire
