#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace fp2_wire {
// Pure, read-only parser of an exact24KiB fctry partition. Requires one
// unambiguous written fac namespace and matching2-byte blob/index per axis.
// Missing, corrupt, transitional or duplicate relevant metadata fails closed.
// Output is untouched on failure. Never initializes NVS or writes storage.
bool load_accel_corrections(const uint8_t *data, size_t len, std::array<int16_t, 3> &out);
struct LightCalibration {
  float low_k{}, low_b{}, high_k{}, high_b{};
  uint32_t low_min{}, low_max{}, high_min{}, high_max{};
};
// Requires all eight exact-length lux blobs; no partial/default calibration.
// Output remains untouched on failure, and no sensitive values are logged.
bool load_light_calibration(const uint8_t *data, size_t len, LightCalibration &out);
}  // namespace fp2_wire
