#include "light_sensor.h"
#if defined(USE_FP2_LIGHT) && defined(USE_ESP32)
#include "esp_partition.h"
#include <vector>
#endif

namespace esphome::fp2 {
#ifdef USE_FP2_LIGHT
bool LightSensor::load_calibration_(::fp2_wire::LightCalibration &out) {
#ifdef USE_ESP32
  const esp_partition_t *partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, "fctry");
  if (partition == nullptr || partition->size != 24 * 1024) {
    this->status_ = "factory_partition_missing";
    return false;
  }
  std::vector<uint8_t> bytes(24 * 1024);
  if (esp_partition_read(partition, 0, bytes.data(), bytes.size()) != ESP_OK ||
      !::fp2_wire::load_light_calibration(bytes.data(), bytes.size(), out)) {
    this->status_ = "factory_validation_failed";
    return false;
  }
  return true;
#else
  (void) out;
  this->status_ = "factory_partition_unavailable";
  return false;
#endif
}
#endif

void LightSensor::setup() {
#ifdef USE_FP2_LIGHT
  this->initialized_ = false;
  this->valid_ = false;
  ::fp2_wire::LightCalibration calibration;
  if (!this->load_calibration_(calibration)) return;
  this->filter_ = ::fp2_wire::LightFilter(calibration);
  const uint8_t configuration[] = {0xc6, 0x10};
  const auto error = this->write_register(0x01, configuration, sizeof(configuration));
  if (error != i2c::ERROR_OK) {
    this->last_read_error_ = static_cast<uint8_t>(error);
    this->status_ = "sensor_initialization_failed";
    return;
  }
  this->initialized_ = true;
  this->status_ = "sampling";
#else
  this->status_ = "disabled";
#endif
}

void LightSensor::loop(uint32_t now) {
#ifdef USE_FP2_LIGHT
  // Local polling/freshness policy, not recovered stock scheduler timing.
  if (!this->initialized_ || now - this->last_sample_at_ < 100) return;
  this->last_sample_at_ = now;
  uint8_t bytes[2];
  const auto error = this->read_register(0x00, bytes, sizeof(bytes));
  if (error != i2c::ERROR_OK) {
    ++this->read_failures_;
    this->last_read_error_ = static_cast<uint8_t>(error);
    this->status_ = "sensor_read_failed";
    return;  // Failed bytes never enter the filter or renew freshness.
  }
  ++this->successful_reads_;
  const uint16_t word = (uint16_t(bytes[0]) << 8) | bytes[1];
  if (this->filter_.update(word)) {
    this->last_update_at_ = now;
    this->valid_ = true;
    this->status_ = "ready";
  } else {
    this->status_ = "sampling";
  }
#else
  (void) now;
#endif
}

bool LightSensor::ready(uint32_t now) const {
  return this->valid_ && now - this->last_update_at_ <= 1000;
}
uint32_t LightSensor::lux() const {
#ifdef USE_FP2_LIGHT
  return this->filter_.lux();
#else
  return 0;  // Readiness remains false without the adapter.
#endif
}
}  // namespace esphome::fp2
