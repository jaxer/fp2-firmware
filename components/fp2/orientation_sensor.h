#pragma once
#include "esphome/core/defines.h"
#include <array>
#include <cstdint>
#ifdef USE_FP2_ORIENTATION
#include "esphome/components/i2c/i2c.h"
#include "orientation.h"
#ifdef USE_ESP32
#include "driver/i2c_master.h"
#endif
#endif

namespace esphome::fp2 {
class OrientationSensor
#ifdef USE_FP2_ORIENTATION
    : protected i2c::I2CDevice
#endif
{
 public:
#ifdef USE_FP2_ORIENTATION
  void set_bus(i2c::I2CBus *bus) { this->set_i2c_bus(bus); this->set_i2c_address(0x27); }
#endif
#if defined(USE_FP2_ORIENTATION) && defined(USE_ESP32)
  void set_native_bus(i2c::InternalI2CBus *bus, uint32_t frequency) {
    this->native_bus_ = bus;
    this->native_frequency_ = frequency;
  }
#endif
  const char *status() const {
#ifdef USE_FP2_ORIENTATION
    return this->status_;
#else
    return "disabled";
#endif
  }
  uint32_t last_native_error() const {
#if defined(USE_FP2_ORIENTATION) && defined(USE_ESP32)
    return this->last_native_error_;
#else
    return 0;
#endif
  }
  uint32_t read_failures() const { return this->read_failures_; }
  uint32_t sample_batches() const { return this->sample_batches_; }
  uint8_t failed_register() const { return this->failed_register_; }
  uint8_t last_read_error() const { return this->last_read_error_; }
  void dump_config() const;
  void setup();
  void loop(uint32_t now);
  bool angle_ready(uint32_t now) const;
  bool orientation_ready(uint32_t now) const;
  uint16_t tilt() const;
  uint8_t direction() const;
 protected:
  uint32_t read_failures_{0};
  uint32_t sample_batches_{0};
  uint8_t failed_register_{0};
  uint8_t last_read_error_{0};
#ifdef USE_FP2_ORIENTATION
  void fail_(uint32_t now);
  i2c::ErrorCode read_accel_register_(uint8_t reg, uint8_t *value, uint8_t length = 1);
#ifdef USE_ESP32
  i2c::ErrorCode write_accel_register_(uint8_t reg, uint8_t value);
  i2c::InternalI2CBus *native_bus_{nullptr};
  i2c_master_dev_handle_t native_device_{nullptr};
  uint32_t native_frequency_{0};
  uint32_t last_native_error_{0};
#endif
  ::fp2_wire::Orientation orientation_;
  std::array<int16_t, 3> corrections_{};
  std::array<std::array<int16_t, 3>, 10> samples_{};
  uint32_t last_sample_at_{0};
  uint32_t last_update_at_{0};
  uint8_t sample_count_{0};
  bool burst_read_{false};
  std::array<uint8_t, 6> probe_single_{}, probe_burst_{};
  bool probe_single_valid_{false}, probe_burst_valid_{false};
  bool range_valid_{false}, mode_valid_{false};
  uint8_t chip_id_{0xff}, range_register_{0xff}, mode_register_{0xff};
  bool initialized_{false};
  const char *status_{"not_initialized"};
  bool valid_{false};
#endif
};
}  // namespace esphome::fp2
