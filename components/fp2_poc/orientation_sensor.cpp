#include "orientation_sensor.h"
#include <cstdio>
#include "esphome/core/log.h"
#ifdef USE_FP2_ORIENTATION
#include "factory_calibration.h"
#include <vector>
#ifdef USE_ESP32
#include "esp_partition.h"
#endif
#endif

namespace esphome::fp2_poc {
#if defined(USE_FP2_ORIENTATION) && defined(USE_ESP32)
namespace {
i2c::ErrorCode native_error(esp_err_t error) {
  if (error == ESP_OK) return i2c::ERROR_OK;
  if (error == ESP_ERR_INVALID_STATE || error == ESP_ERR_INVALID_RESPONSE)
    return i2c::ERROR_NOT_ACKNOWLEDGED;
  if (error == ESP_ERR_TIMEOUT) return i2c::ERROR_TIMEOUT;
  if (error == ESP_ERR_INVALID_ARG) return i2c::ERROR_INVALID_ARGUMENT;
  return i2c::ERROR_UNKNOWN;
}
}  // namespace
#endif
void OrientationSensor::setup() {
#ifdef USE_FP2_ORIENTATION
#ifdef USE_ESP32
  const esp_partition_t *partition = esp_partition_find_first(ESP_PARTITION_TYPE_ANY,
                                                            ESP_PARTITION_SUBTYPE_ANY, "fctry");
  if (partition == nullptr || partition->size != 24 * 1024) {
    this->status_ = "factory_partition_missing";
    ESP_LOGE("fp2.orientation", "Factory partition unavailable");
    return;
  }
  {
    std::vector<uint8_t> data(24 * 1024);
    if (esp_partition_read(partition, 0, data.data(), data.size()) != ESP_OK ||
        !::fp2_wire::load_accel_corrections(data.data(), data.size(), this->corrections_)) {
      this->status_ = "factory_validation_failed";
      ESP_LOGE("fp2.orientation", "Factory calibration read/CRC validation failed");
      return;
    }
  }  // Release factory bytes before sampling; never log calibration values.
  if (this->native_bus_ != nullptr) {
    i2c_master_bus_handle_t bus = nullptr;
    const esp_err_t found = i2c_master_get_bus_handle(static_cast<i2c_port_t>(this->native_bus_->get_port()), &bus);
    i2c_device_config_t config{};
    config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    config.device_address = 0x27;
    config.scl_speed_hz = this->native_frequency_;
    config.scl_wait_us = 13000;
    if (found != ESP_OK ||
        i2c_master_bus_add_device(bus, &config, &this->native_device_) != ESP_OK) {
      this->status_ = "native_bus_initialization_failed";
      ESP_LOGE("fp2.orientation", "Native accelerometer device initialization failed");
      return;
    }
  }
  const uint8_t power = 0x0e;
  const uint8_t range = 0x40;
  if (this->write_accel_register_(0x11, power) != i2c::ERROR_OK ||
      this->write_accel_register_(0x0f, range) != i2c::ERROR_OK) {
    this->status_ = "sensor_initialization_failed";
    ESP_LOGE("fp2.orientation", "Accelerometer initialization failed");
    return;
  }
  // DA218B Rev0.4 permits sequential data reads; identify this unit before
  // selecting that transfer. Failed/unknown identity retains single reads.
  const bool identity_ok = this->read_accel_register_(0x01, &this->chip_id_) == i2c::ERROR_OK;
  this->range_valid_ = this->read_accel_register_(0x0f, &this->range_register_) == i2c::ERROR_OK;
  this->mode_valid_ = this->read_accel_register_(0x11, &this->mode_register_) == i2c::ERROR_OK;
  this->probe_single_valid_ = true;
  for (uint8_t index = 0; index < 6; index++) {
    if (this->read_accel_register_(0x02 + index, &this->probe_single_[index]) != i2c::ERROR_OK) {
      this->probe_single_valid_ = false;
      break;
    }
  }
  this->burst_read_ = identity_ok && this->chip_id_ == 0x13;
  if (this->burst_read_)
    this->probe_burst_valid_ = this->read_accel_register_(0x02, this->probe_burst_.data(), 6) == i2c::ERROR_OK;
  this->initialized_ = true;
  this->status_ = "sampling";
#endif
#endif
}

void OrientationSensor::loop(uint32_t now) {
#ifdef USE_FP2_ORIENTATION
  if (!this->initialized_ || now - this->last_sample_at_ < 10)
    return;
  this->last_sample_at_ = now;
  uint8_t registers[6];
  if (this->burst_read_) {
    const auto error = this->read_accel_register_(0x02, registers, 6);
    if (error != i2c::ERROR_OK) {
      this->read_failures_++;
      this->failed_register_ = 0x02;  // Starting register, not the failed byte.
      this->last_read_error_ = static_cast<uint8_t>(error);
      this->fail_(now);
      return;
    }
  } else for (uint8_t index = 0; index < 6; index++) {
    const auto error = this->read_accel_register_(0x02 + index, &registers[index]);
    if (error != i2c::ERROR_OK) {
      this->read_failures_++;
      this->failed_register_ = 0x02 + index;
      this->last_read_error_ = static_cast<uint8_t>(error);
      this->fail_(now);
      return;
    }
  }
  for (size_t axis = 0; axis < 3; axis++) {
    const uint16_t raw = (uint16_t(registers[axis * 2]) >> 4) |
                         (uint16_t(registers[axis * 2 + 1]) << 4);
    this->samples_[this->sample_count_][axis] =
        raw & 0x0800 ? static_cast<int16_t>(int32_t(raw) - 4096) : static_cast<int16_t>(raw);
  }
  if (++this->sample_count_ == this->samples_.size()) {
    this->sample_count_ = 0;
    this->sample_batches_++;
    // Debounce history belongs to a continuous stream of fresh measurements.
    if (now - this->last_update_at_ > 1000)
      this->orientation_ = ::fp2_wire::Orientation{};
    this->valid_ = this->orientation_.update(this->samples_, this->corrections_, now);
    if (this->valid_) {
      this->last_update_at_ = now;
      this->status_ = this->orientation_.orientation_ready() ? "ready" : "awaiting_orientation_class";
    } else {
      this->status_ = "invalid_sample_batch";
    }
  }
#endif
}

#ifdef USE_FP2_ORIENTATION
i2c::ErrorCode OrientationSensor::read_accel_register_(uint8_t reg, uint8_t *value, uint8_t length) {
#ifdef USE_ESP32
  if (this->native_bus_ != nullptr) {
    if (this->native_device_ == nullptr) return i2c::ERROR_NOT_INITIALIZED;
    const esp_err_t error = i2c_master_transmit_receive(this->native_device_, &reg, 1, value, length, 100);
    if (error != ESP_OK) this->last_native_error_ = static_cast<uint32_t>(error);
    return native_error(error);
  }
#endif
  return this->read_register(reg, value, length);
}
#ifdef USE_ESP32
i2c::ErrorCode OrientationSensor::write_accel_register_(uint8_t reg, uint8_t value) {
  if (this->native_bus_ != nullptr) {
    if (this->native_device_ == nullptr) return i2c::ERROR_NOT_INITIALIZED;
    const uint8_t bytes[] = {reg, value};
    const esp_err_t error = i2c_master_transmit(this->native_device_, bytes, sizeof(bytes), 100);
    if (error != ESP_OK) this->last_native_error_ = static_cast<uint32_t>(error);
    return native_error(error);
  }
  return this->write_register(reg, &value, 1);
}
#endif
void OrientationSensor::fail_(uint32_t now) {
  // A failed partial sample is not a new observation. Preserve only the last
  // complete real batch within its original freshness window; never renew it.
  this->status_ = "sensor_read_failed";
  this->sample_count_ = 0;
  if (!this->valid_ || now - this->last_update_at_ > 1000) {
    this->valid_ = false;
    this->orientation_ = ::fp2_wire::Orientation{};
  }
}
#endif

bool OrientationSensor::angle_ready(uint32_t now) const {
#ifdef USE_FP2_ORIENTATION
  return this->valid_ && now - this->last_update_at_ <= 1000 && this->orientation_.angle_ready();
#else
  return false;
#endif
}
bool OrientationSensor::orientation_ready(uint32_t now) const {
#ifdef USE_FP2_ORIENTATION
  return this->valid_ && now - this->last_update_at_ <= 1000 && this->orientation_.orientation_ready();
#else
  return false;
#endif
}
uint16_t OrientationSensor::tilt() const {
#ifdef USE_FP2_ORIENTATION
  return this->orientation_.tilt();
#else
  return 0;  // Unreachable on the wire: readiness is always false without the adapter.
#endif
}
uint8_t OrientationSensor::direction() const {
#ifdef USE_FP2_ORIENTATION
  return this->orientation_.direction();
#else
  return 0;  // Unreachable on the wire: readiness is always false without the adapter.
#endif
}
}  // namespace esphome::fp2_poc

namespace esphome::fp2_poc {
void OrientationSensor::dump_config() const {
#ifdef USE_FP2_ORIENTATION
  ESP_LOGI("fp2.orientation", "Accelerometer identity: chip_id=0x%02x transfer=%s range=0x%02x/%s mode=0x%02x/%s",
           this->chip_id_, this->burst_read_ ? "six_byte" : "single_byte",
           this->range_register_, this->range_valid_ ? "read" : "unknown",
           this->mode_register_, this->mode_valid_ ? "read" : "unknown");
  char single[13], bulk[13];
  for (unsigned i = 0; i < 6; i++) {
    std::snprintf(single + i * 2, 3, "%02x", this->probe_single_[i]);
    std::snprintf(bulk + i * 2, 3, "%02x", this->probe_burst_[i]);
  }
  ESP_LOGI("fp2.orientation", "Accelerometer raw probes: single=%s/%s burst=%s/%s",
           single, this->probe_single_valid_ ? "read" : "unknown",
           bulk, this->probe_burst_valid_ ? "read" : "unknown");
#endif
}
}  // namespace esphome::fp2_poc
