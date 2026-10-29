#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace fp2_wire {
struct Frame {
  uint8_t sequence{};
  uint8_t operation{};
  std::vector<uint8_t> payload;
};

// RX only. Storage is bounded to one maximum-sized frame (2058 bytes).
// No clock/timeout: a later complete CRC-valid frame can replace a truncated
// candidate. An embedded valid frame is consequently ambiguous until completion.
class Parser {
 public:
  Parser() { buffer_.reserve(2058); }
  bool feed(uint8_t byte, Frame &frame);
  uint32_t good_frames() const { return good_; }
  uint32_t rejected_frames() const { return rejected_; }
 private:
  std::vector<uint8_t> buffer_;
  uint32_t good_{};
  uint32_t rejected_{};
};

// Exact scalar payload sizes only; rejects op1, containers and unsupported tags.
// Output arguments remain unchanged on failure. Tag4 normalizes nonzero to1.
bool decode_scalar(const Frame &frame, uint16_t &id, uint8_t &type, uint32_t &value);
}  // namespace fp2_wire
