#include "occupancy.h"

namespace fp2_wire {
bool Occupancy::ingest(const ::fp2_wire::Frame &frame, uint32_t now_ms) {
  if (frame.operation != 4 && frame.operation != 5) return false;
  uint16_t id;
  uint8_t type;
  uint32_t value;
  if (!::fp2_wire::decode_scalar(frame, id, type, value)) return false;
  OccupancyState *state;
  if (id == 0x0104 && type == 0 && value <= 1) {
    state = &room_;
  } else if (id == 0x0142 && type == 1) {
    const uint32_t zone_id = value >> 8;
    const uint32_t status = value & 0xff;
    if (zone_id < 1 || zone_id > 30 || status > 1) return false;
    state = &zones_[zone_id - 1];
    value = status;
  } else {
    return false;
  }
  state->known = true;
  state->occupied = value == 1;
  state->updated_ms = now_ms;
  return true;
}

bool Occupancy::tick(uint32_t now_ms) {
  if (timeout_ms_ == 0) return false;
  bool changed = false;
  auto expire = [&](OccupancyState &state) {
    if (state.known && uint32_t(now_ms - state.updated_ms) >= timeout_ms_) {
      state.known = false;
      changed = true;
    }
  };
  expire(room_);
  for (auto &state : zones_) expire(state);
  return changed;
}

void Occupancy::invalidate() {
  room_.known = false;
  invalidate_zones();
}

void Occupancy::invalidate_zone(uint32_t id) {
  if (id >= 1 && id <= 30) zones_[id - 1].known = false;
}

void Occupancy::invalidate_zones() {
  for (auto &state : zones_) state.known = false;
}

void Occupancy::seed_native_cache(const NativeSnapshot &snapshot, uint32_t now_ms) {
  for (size_t i = 0; i < zones_.size(); ++i) {
    const auto &observed = snapshot.zones[i];
    if (!zones_[i].known && observed.known)
      zones_[i] = {true, observed.occupied, now_ms};
  }
}

const OccupancyState &Occupancy::zone(uint8_t id) const {
  return id >= 1 && id <= 30 ? zones_[id - 1] : invalid_;
}
}  // namespace fp2_wire
