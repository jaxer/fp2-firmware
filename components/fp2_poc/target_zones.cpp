#include "target_zones.h"
#include <utility>

namespace fp2_wire {
namespace {
// C++ integer division truncates toward zero; grid indexing requires floor.
int floor50(int value) {
  const int quotient = value / 50;
  return quotient - (value < 0 && value % 50 != 0);
}
bool cell(const std::array<uint8_t, 40> &grid, int row, int column) {
  if (row < 0 || row >= 20 || column < 0 || column >= 16) return false;
  const unsigned index = unsigned(row * 16 + column);
  return (grid[index / 8] & (1u << (7 - index % 8))) != 0;
}
}  // namespace

bool TargetZones::configure(uint8_t id, const std::array<uint8_t, 40> &grid) {
  if (id < 1 || id > 30) return false;
  grids_[id - 1] = grid;
  configured_[id - 1] = true;
  states_[id - 1] = OccupancyState{};
  return true;
}

bool TargetZones::ingest(const Frame &frame, uint32_t now_ms) {
  uint16_t attribute;
  uint8_t type;
  uint32_t value;
  if ((frame.operation == 4 || frame.operation == 5) &&
      decode_scalar(frame, attribute, type, value) &&
      attribute == 0x0104 && type == 0 && value <= 1) {
    // A zone is a spatial subset of this room. Explicit authoritative empty
    // clears all configured subsets; room occupied says nothing about subsets.
    if (value == 0) {
      // Authoritative room vacancy does not manufacture an0117 snapshot.
      snapshot_known_ = false;
      for (size_t z = 0; z < states_.size(); ++z) {
        if (configured_[z]) states_[z] = {true, false, now_ms};
      }
    }
    return true;
  }
  TargetSnapshot snapshot;
  if (!decode_targets(frame, snapshot)) return false;
  snapshot_ = std::move(snapshot);
  snapshot_known_ = true;
  ++snapshot_revision_;
  // Retain the geometric model's explicit MVP work bound. The shared decoder
  // accepts the full transport bound and makes no radar capacity claim.
  if (snapshot_.targets.size() > 32) {
    invalidate_geometry();
    return false;
  }
  for (size_t z = 0; z < states_.size(); ++z) {
    if (!configured_[z]) continue;
    bool definite = false;
    bool uncertain = false;
    for (const auto &target : snapshot_.targets) {
      const uint8_t flag = target.flag_raw;
      if (flag != 0 && flag != 255) continue;
      const int a = target.a_hundredths;
      const int b = target.b_hundredths;
      // ±2 reported centi-units overapproximates truncation/float rounding.
      // Inclusive intervals intentionally retain both cells at boundaries.
      const int first_row = floor50(b - 2);
      const int last_row = floor50(b + 2);
      const int first_column = floor50(400 - (a + 2));
      const int last_column = floor50(400 - (a - 2));
      bool any_inside = false;
      bool all_inside = true;
      for (int row = first_row; row <= last_row; ++row) {
        for (int column = first_column; column <= last_column; ++column) {
          const bool inside = cell(grids_[z], row, column);
          any_inside |= inside;
          all_inside &= inside;
        }
      }
      if (flag == 0 && all_inside) definite = true;
      else if (any_inside) uncertain = true;
    }
    states_[z].known = definite || !uncertain;
    states_[z].occupied = definite;
    states_[z].updated_ms = now_ms;
  }
  return true;
}

void TargetZones::invalidate() {
  snapshot_known_ = false;
  invalidate_geometry();
}

void TargetZones::invalidate_geometry() {
  for (auto &state : states_) state.known = false;
}

const OccupancyState &TargetZones::zone(uint8_t id) const {
  return id >= 1 && id <= 30 && configured_[id - 1] ? states_[id - 1] : invalid_;
}
}  // namespace fp2_wire
