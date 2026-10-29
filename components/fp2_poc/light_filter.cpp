#include "light_filter.h"
#include <cmath>
#include <limits>

namespace fp2_wire {
namespace {
// Normal factory coefficients cannot overflow, but reject nonfinite inputs and
// saturate before conversion so malformed callers never cause cast UB.
int32_t truncate(double value) {
  if (std::isnan(value)) return 0;
  if (value >= std::numeric_limits<int32_t>::max()) return std::numeric_limits<int32_t>::max();
  if (value <= std::numeric_limits<int32_t>::min()) return std::numeric_limits<int32_t>::min();
  return static_cast<int32_t>(value);
}
int32_t calibrated(uint32_t value, float k, float b) {
  volatile float product = static_cast<float>(value) * k;
  volatile float sum = product + b;  // Preserve two stock operations even with FMA enabled.
  return truncate(sum);
}
int32_t fallback(uint32_t value, double k, double b) {
  volatile double product = static_cast<double>(value) * k;
  return truncate(product + b);
}
}  // namespace

uint32_t LightFilter::decode(uint16_t word) {
  const uint32_t product = (uint32_t{1} << (word >> 12)) * (word & 0xfff);
  return static_cast<uint32_t>(static_cast<double>(product) * 0.01);
}

uint32_t LightFilter::correct(uint32_t reading) const {
  if (!reading) return 0;
  const auto &c = calibration_;
  const bool available = (c.low_max && c.low_k > 0) || (c.high_max && c.high_k > 0);
  int32_t result;
  if (!available) {
    result = fallback(reading, 3.855, 1.4);
    if (result > 160) result = fallback(reading, 3.876, 2.9);
  } else if (c.low_max && c.low_k > 0 && !c.high_max && static_cast<double>(c.high_k) < 1e-6) {
    result = calibrated(reading, c.low_k, c.low_b);
    if (static_cast<uint32_t>(result) > c.low_max) result = fallback(reading, 3.876, 2.9);
  } else if (!c.low_max && static_cast<double>(c.low_k) < 1e-6 && c.high_max && c.high_k > 0) {
    result = calibrated(reading, c.high_k, c.high_b);
    if (static_cast<uint32_t>(result) < c.high_min) result = fallback(reading, 3.855, 1.4);
  } else {
    result = reading <= c.low_max ? calibrated(reading, c.low_k, c.low_b)
                                : calibrated(reading, c.high_k, c.high_b);
  }
  if (result < 0) return 0;
  return result > 83000 ? 83000 : static_cast<uint32_t>(result);
}

bool LightFilter::update(uint16_t word) {
  if (discarded_ < 10) { ++discarded_; return false; }
  const uint32_t current = decode(word);
  samples_[next_] = current;
  next_ = static_cast<uint8_t>((next_ + 1) % samples_.size());
  if (filled_ < 10) ++filled_;
  if (filled_ < 10) return false;
  uint32_t maximum = samples_[0], minimum = samples_[0], sum = 0, count = 0;
  for (uint32_t sample : samples_) {
    if (sample) { sum += sample; ++count; }
    if (sample > maximum) maximum = sample;
    if (sample && sample < minimum) minimum = sample;
  }
  uint32_t reading = current;
  if (count >= 3) reading = (sum - maximum - minimum) / (count - 2);
  else if (count) reading = sum / count;
  lux_ = correct(reading);
  return true;
}
}  // namespace fp2_wire
