#pragma once
#include "protocol.h"
#include <string>

namespace fp2_commands {
// Exactly80 ASCII hex characters; invalid input leaves output unchanged.
bool decode_mask_hex(const std::string &hex, std::vector<uint8_t> &output);
// Pure op2 builders. All numeric inputs are checked before narrowing. Invalid
// requests leave output unchanged. Sequence belongs to the caller's scheduler.
bool zone_geometry(uint32_t sequence, uint32_t zone, const uint8_t *map,
                   size_t length, fp2_wire::Frame &output);
bool special_map(uint32_t sequence, uint32_t id, const uint8_t *map,
                 size_t length, fp2_wire::Frame &output);
bool scalar_control(uint32_t sequence, uint32_t id, uint32_t value,
                    fp2_wire::Frame &output);
// Raw wire values:0151 permits supported numeric sensitivity1..3 (no physical labels);
// 0152 permits stock category indices0..39, without human category labels;
// 0153 permits raw0/1 (radar stores raw==0). No zone0 or implicit polarity.
bool zone_property(uint32_t sequence, uint32_t id, uint32_t zone,
                   uint32_t value, fp2_wire::Frame &output);
}  // namespace fp2_commands
