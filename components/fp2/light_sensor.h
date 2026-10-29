#pragma once
#include "esphome/core/defines.h"
#include <cstdint>
#ifdef USE_FP2_LIGHT
#include "esphome/components/i2c/i2c.h"
#include "light_filter.h"
#endif

namespace esphome::fp2 {
class LightSensor
#ifdef USE_FP2_LIGHT
    : protected i2c::I2CDevice
#endif
{
 public:
#ifdef USE_FP2_LIGHT
  LightSensor() { this->set_i2c_address(0x44); }
  void set_bus(i2c::I2CBus *bus) { this->set_i2c_bus(bus); }
#endif
  virtual ~LightSensor() = default;
  void setup();
  void loop(uint32_t now);
  bool ready(uint32_t now) const;
  uint32_t lux() const;
  const char *status() const { return this->status_; }
  uint32_t read_failures() const { return this->read_failures_; }
  uint32_t successful_reads() const { return this->successful_reads_; }
  uint8_t last_read_error() const { return this->last_read_error_; }
 protected:
#ifdef USE_FP2_LIGHT
  // Platform storage seam: production reads fctry; host tests supply retained
  // partition bytes to the same validated loader. Never initializes NVS.
  virtual bool load_calibration_(::fp2_wire::LightCalibration &out);
  ::fp2_wire::LightFilter filter_;
#endif
  uint32_t last_sample_at_{0};
  uint32_t last_update_at_{0};
  uint32_t read_failures_{0};
  uint32_t successful_reads_{0};
  uint8_t last_read_error_{0};
  bool initialized_{false};
  bool valid_{false};
  const char *status_{"not_initialized"};
};
}  // namespace esphome::fp2
