#include "normal_commands.h"
#include <utility>

namespace fp2_commands {
namespace {
bool valid_map(uint32_t sequence, const uint8_t *map, size_t length) {
  return sequence <= 255 && map != nullptr && length == 40;
}
fp2_wire::Frame start(uint32_t sequence, uint32_t id, uint8_t tag) {
  return {static_cast<uint8_t>(sequence), 2,
          {static_cast<uint8_t>(id >> 8), static_cast<uint8_t>(id), tag}};
}
}  // namespace

bool decode_mask_hex(const std::string &hex, std::vector<uint8_t> &output) {
  if (hex.size() != 80) return false;
  auto nibble = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  std::vector<uint8_t> decoded;
  decoded.reserve(40);
  for (size_t i = 0; i < hex.size(); i += 2) {
    const int high = nibble(hex[i]), low = nibble(hex[i + 1]);
    if (high < 0 || low < 0) return false;
    decoded.push_back(static_cast<uint8_t>((high << 4) | low));
  }
  output = std::move(decoded);
  return true;
}

bool zone_geometry(uint32_t sequence, uint32_t zone, const uint8_t *map,
                   size_t length, fp2_wire::Frame &output) {
  if (zone < 1 || zone > 30 || !valid_map(sequence, map, length)) return false;
  auto result = start(sequence, 0x0114, 6);
  result.payload.insert(result.payload.end(), {0, 41, static_cast<uint8_t>(zone)});
  result.payload.insert(result.payload.end(), map, map + length);
  output = std::move(result);
  return true;
}

bool special_map(uint32_t sequence, uint32_t id, const uint8_t *map,
                 size_t length, fp2_wire::Frame &output) {
  if ((id != 0x0107 && id != 0x0109 && id != 0x0110) ||
      !valid_map(sequence, map, length)) return false;
  auto result = start(sequence, id, 6);
  result.payload.insert(result.payload.end(), {0, 40});
  result.payload.insert(result.payload.end(), map, map + length);
  output = std::move(result);
  return true;
}

bool scalar_control(uint32_t sequence, uint32_t id, uint32_t value,
                    fp2_wire::Frame &output) {
  uint32_t maximum;
  switch (id) {
    case 0x0106: case 0x0122: maximum = 2; break;
    case 0x0111: case 0x0170: maximum = 3; break;
    default: return false;
  }
  if (sequence > 255 || value > maximum) return false;
  auto result = start(sequence, id, 0);
  result.payload.push_back(static_cast<uint8_t>(value));
  output = std::move(result);
  return true;
}

bool zone_property(uint32_t sequence, uint32_t id, uint32_t zone,
                   uint32_t value, fp2_wire::Frame &output) {
  if (sequence > 255 || zone < 1 || zone > 30) return false;
  switch (id) {
    case 0x0151: if (value < 1 || value > 3) return false; break;
    case 0x0152: if (value > 39) return false; break;
    case 0x0153: if (value > 1) return false; break;
    default: return false;
  }
  auto result = start(sequence, id, 1);
  result.payload.insert(result.payload.end(),
                        {static_cast<uint8_t>(zone), static_cast<uint8_t>(value)});
  output = std::move(result);
  return true;
}
}  // namespace fp2_commands
