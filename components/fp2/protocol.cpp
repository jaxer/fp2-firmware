#include "protocol.h"

// Wire grammar: docs/uart-transport.md; scalar tags independently proved in
// docs/mss-parser-contract.md. Deliberately stricter than stock length guards.

namespace fp2_wire {
namespace {
constexpr size_t MAX_PAYLOAD = 2048;
constexpr size_t MAX_FRAME = MAX_PAYLOAD + 10;
uint16_t crc16(const uint8_t *data, size_t size) {
  uint16_t crc = 0xffff;
  for (size_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc & 1) ? (crc >> 1) ^ 0xa001 : crc >> 1;
  }
  return crc;
}
// 0=incomplete, -1=invalid, positive=complete frame length.
int candidate(const std::vector<uint8_t> &b, size_t p) {
  const size_t available = b.size() - p;
  if (available < 8) return 0;
  const size_t n = (size_t(b[p + 5]) << 8) | b[p + 6];
  unsigned sum = 0;
  for (size_t i = 0; i < 8; ++i) sum += b[p + i];
  if (n > MAX_PAYLOAD || (sum & 255) != 0) return -1;
  const size_t total = n + 10;
  if (available < total) return 0;
  const uint16_t expected = uint16_t(b[p + total - 2]) |
                            (uint16_t(b[p + total - 1]) << 8);
  return crc16(b.data() + p, total - 2) == expected ? int(total) : -1;
}
bool sync(const std::vector<uint8_t> &b, size_t p) {
  return p + 3 <= b.size() && b[p] == 0x55 && b[p + 1] == 0 && b[p + 2] == 1;
}
}  // namespace

bool Parser::feed(uint8_t byte, Frame &frame) {
  if (buffer_.size() == MAX_FRAME) {
    buffer_.erase(buffer_.begin());
    ++rejected_;
  }
  buffer_.push_back(byte);
  while (buffer_.size() >= 3) {
    size_t p = 0;
    while (p + 3 <= buffer_.size() && !sync(buffer_, p)) ++p;
    if (p) buffer_.erase(buffer_.begin(), buffer_.begin() + p);
    if (buffer_.size() < 3) return false;
    int total = candidate(buffer_, 0);
    if (total < 0) {
      ++rejected_;
      buffer_.erase(buffer_.begin());
      continue;
    }
    size_t start = 0;
    if (total == 0) {
      // Check later syncs only for a fully validated recovery frame. Invalid
      // embedded candidates never discard an earlier incomplete candidate.
      for (size_t next = 1; next + 10 <= buffer_.size(); ++next) {
        if (!sync(buffer_, next)) continue;
        const int found = candidate(buffer_, next);
        if (found > 0) {
          start = next;
          total = found;
          ++rejected_;
          break;
        }
      }
      if (total == 0) return false;
    }
    frame.sequence = buffer_[start + 3];
    frame.operation = buffer_[start + 4];
    frame.payload.assign(buffer_.begin() + start + 8,
                         buffer_.begin() + start + total - 2);
    buffer_.erase(buffer_.begin(), buffer_.begin() + start + total);
    ++good_;
    return true;
  }
  return false;
}

bool decode_scalar(const Frame &frame, uint16_t &id, uint8_t &type, uint32_t &value) {
  const auto &p = frame.payload;
  if (frame.operation == 1 || p.size() < 4) return false;
  const uint8_t tag = p[2];
  size_t bytes;
  switch (tag) {
    case 0: case 4: bytes = 1; break;
    case 1: bytes = 2; break;
    case 2: bytes = 4; break;
    default: return false;
  }
  if (p.size() != bytes + 3) return false;
  uint32_t scalar = 0;
  for (size_t i = 3; i < p.size(); ++i) scalar = (scalar << 8) | p[i];
  if (tag == 4) scalar = scalar != 0;
  id = (uint16_t(p[0]) << 8) | p[1];
  type = tag;
  value = scalar;
  return true;
}
}  // namespace fp2_wire
