#include "orientation.h"
#include <cmath>
#include <limits>

namespace fp2_wire {
namespace {
int16_t narrow16(int32_t value) {
  const uint16_t bits = static_cast<uint16_t>(value);
  return static_cast<int16_t>(bits < 32768 ? int32_t(bits) : int32_t(bits) - 65536);
}
int angle(double axis, double other_a, double other_b) {
  const double denominator = std::sqrt(other_a * other_a + other_b * other_b);
  const double ratio = denominator == 0.0 ? std::copysign(std::numeric_limits<double>::infinity(), axis)
                                           : axis / denominator;
  // Stock signed ROM conversion truncates toward zero after adding0.5.
  return static_cast<int>(std::atan(ratio) * 180.0 / 3.1416 + 0.5);
}
uint8_t classify(int x, int y, int z) {
  uint8_t state = 8;
  if (z < -69 && y >= -19 && y <= 19 && x >= -19 && x <= 19) state = 0;
  if (z >= -69 && z <= -21 && y >= -19 && y <= 19 && std::abs(x) > 20)
    state = x < 0 ? 1 : 2;
  if (z > 70 && y >= -19 && y <= 19 && x >= -19 && x <= 19) state = 5;
  if (z >= -20 && z <= 19 && y >= -19 && y <= 19 && std::abs(x) > 50)
    state = x < 0 ? 3 : 4;
  if (z >= 20 && z <= 70 && y >= -19 && y <= 19 && x >= -69 && x <= 69)
    state = x < 0 ? 6 : 7;
  return state;
}
}  // namespace

void Orientation::invalidate() {
  angle_ready_ = false;
  orientation_ready_ = false;
  invalid_count_ = departure_36_ = departure_47_ = departure_5_ = 0;
}

bool Orientation::update(const std::array<std::array<int16_t, 3>, 10> &raw,
                         const std::array<int16_t, 3> &correction, uint32_t now_ms) {
  std::array<int32_t, 3> sum{};
  for (const auto &sample : raw) {
    for (size_t axis = 0; axis < 3; ++axis) {
      if (sample[axis] < -2048 || sample[axis] > 2047) {
        invalidate();
        return false;
      }
      sum[axis] += sample[axis];
    }
  }
  std::array<int16_t, 3> mean{}, corrected{};
  for (size_t axis = 0; axis < 3; ++axis) {
    mean[axis] = static_cast<int16_t>(sum[axis] / 10);
    corrected[axis] = narrow16(int32_t(mean[axis]) + correction[axis]);
  }
  // Deliberate MVP sensor-validity boundary: do not turn an allzero batch
  // into a ready90-degree observation solely because stock's guard matches.
  if (mean[0] == 0 && mean[1] == 0 && mean[2] == 0) {
    invalidate();
    return false;
  }
  int x = 0, y = 0, z = 0;
  if (mean[0] != mean[1] && mean[1] != mean[2] && mean[0] != mean[2]) {
    if (corrected[0] == 0 && corrected[1] == 0 && corrected[2] == 0) {
      invalidate();
      return false;
    }
    // Stock crosses the first two angle labels: Xraw -> angleY, Yraw -> angleX.
    x = angle(corrected[1], corrected[0], corrected[2]);
    y = angle(corrected[0], corrected[1], corrected[2]);
    z = angle(corrected[2], corrected[0], corrected[1]);
  }
  tilt_ = static_cast<uint16_t>(90 - std::abs(z));
  angle_ready_ = true;
  last_update_ms_ = now_ms;
  accept(classify(x, y, z));
  return true;
}

void Orientation::accept(uint8_t candidate) {
  if (candidate == 8) {
    ++invalid_count_;
    if (invalid_count_ >= 30) {
      direction_ = 8;
      orientation_ready_ = true;
      invalid_count_ = 0;
    }
    departure_36_ = departure_47_ = departure_5_ = 0;
    return;
  }
  invalid_count_ = 0;
  auto departure = [&](uint16_t &count, bool applies) {
    if (!applies) {
      count = 0;
      return;
    }
    if (++count < 5) candidate = direction_;
    else count = 0;
  };
  // Preserve stock's gate order: later gates see any earlier held candidate.
  departure(departure_36_, orientation_ready_ && (direction_ == 3 || direction_ == 6) && candidate != direction_);
  departure(departure_47_, orientation_ready_ && (direction_ == 4 || direction_ == 7) && candidate != direction_);
  departure(departure_5_, orientation_ready_ && direction_ == 5 && candidate != 5);
  direction_ = candidate;
  orientation_ready_ = true;
}
}  // namespace fp2_wire
