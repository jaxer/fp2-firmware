#include "targets.h"
#include <algorithm>
#include <utility>

namespace fp2_wire {
namespace {
uint16_t be16(const uint8_t *p) {
  return static_cast<uint16_t>((uint16_t(p[0]) << 8) | p[1]);
}
int16_t signed_be16(const uint8_t *p) {
  const int32_t value = be16(p);
  return static_cast<int16_t>(value >= 32768 ? value - 65536 : value);
}
}  // namespace
bool decode_targets(const Frame &frame, TargetSnapshot &output) {
  const auto &p = frame.payload;
  if (frame.operation != 5 || p.size() < 6 || p.size() > 2048 ||
      p[0] != 1 || p[1] != 0x17 || p[2] != 6) return false;
  const size_t declared = be16(p.data() + 3);
  const size_t count = p[5];
  if (declared != 1 + 14 * count || p.size() != 5 + declared) return false;
  TargetSnapshot result;
  result.sequence = frame.sequence;
  result.targets.reserve(count);
  for (size_t i = 0; i < count; ++i) {
    const auto *record = p.data() + 6 + 14 * i;
    Target target;
    target.id = record[0];
    target.a_hundredths = signed_be16(record + 1);
    target.b_hundredths = signed_be16(record + 3);
    target.field_5_6_raw = be16(record + 5);
    target.magnitude_raw = be16(record + 7);
    target.scaled_field_raw = be16(record + 9);
    target.flag_raw = record[11];
    target.r29_or_ff_raw = record[12];
    target.r30_raw = record[13];
    std::copy(record, record + 14, target.raw.begin());
    result.targets.push_back(target);
  }
  output = std::move(result);
  return true;
}
}  // namespace fp2_wire
