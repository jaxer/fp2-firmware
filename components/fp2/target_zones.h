#pragma once
#include "occupancy.h"
#include "targets.h"
#include <array>

namespace fp2_wire {
// Host-defined geometric occupancy, distinct from native0142 hold/debounce.
class TargetZones {
 public:
  bool configure(uint8_t id, const std::array<uint8_t, 40> &grid);
  // Strict0117/op5 snapshots or0104/op4/op5 authoritative room0/1.
  // Accepted repeated snapshots return true. Malformed input changes nothing.
  // Valid snapshots above the32-target geometric work bound update tracking
  // data but return false and invalidate geometric zone state.
  bool ingest(const Frame &frame, uint32_t now_ms);
  void invalidate();
  void invalidate_geometry();
  const TargetSnapshot &latest_snapshot() const { return snapshot_; }
  bool snapshot_known() const { return snapshot_known_; }
  uint32_t snapshot_revision() const { return snapshot_revision_; }
  const OccupancyState &zone(uint8_t id) const;
 private:
  TargetSnapshot snapshot_;
  bool snapshot_known_{false};
  uint32_t snapshot_revision_{0};
  std::array<std::array<uint8_t, 40>, 30> grids_{};
  std::array<bool, 30> configured_{};
  std::array<OccupancyState, 30> states_{};
  const OccupancyState invalid_{};
};
}  // namespace fp2_wire
