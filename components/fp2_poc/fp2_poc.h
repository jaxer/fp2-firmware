#pragma once

#include "esphome/core/component.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "protocol.h"
#include "esphome/core/defines.h"
#ifdef USE_FP2_TARGET_EVENTS
#include "esphome/components/api/custom_api_device.h"
#endif
#include "normal_commands.h"
#include "occupancy.h"
#include "target_zones.h"
#include "orientation_sensor.h"
#include "light_sensor.h"
#include "learning.h"
#include "configuration_reader.h"
#include <array>
#include <deque>

namespace esphome::fp2_poc {

// Protected UART inheritance exposes only parent registration, not TX helpers.
class FP2PoC : public Component, protected uart::UARTDevice
#ifdef USE_FP2_TARGET_EVENTS
    , protected api::CustomAPIDevice
#endif
{
 public:
  using uart::UARTDevice::set_uart_parent;
  std::string configuration_result() const { return this->radar_configuration_sensor_ == nullptr ? "unknown" : this->radar_configuration_sensor_->state; }
  std::string configuration_status() const { return this->configuration_status_sensor_ == nullptr ? "unknown" : this->configuration_status_sensor_->state; }
  std::string learning_status() const { return this->learning_status_sensor_ == nullptr ? "unknown" : this->learning_status_sensor_->state; }
  std::string edge_candidate() const { return this->auto_edge_candidate_sensor_ == nullptr ? "unknown" : this->auto_edge_candidate_sensor_->state; }
  void set_target_count(sensor::Sensor *value) { this->target_count_sensor_ = value; }
  void set_measured_tilt(sensor::Sensor *value) { this->measured_tilt_sensor_ = value; }
  void set_mounting_direction(sensor::Sensor *value) { this->mounting_direction_sensor_ = value; }
  void set_orientation_read_failures(sensor::Sensor *value) { this->orientation_failures_sensor_ = value; }
  void set_diagnostic_interval(uint32_t value) { this->diagnostic_interval_ms_ = value; }
  void set_enable_orientation(bool value) { this->enable_orientation_ = value; }
#ifdef USE_FP2_LIGHT
  void set_light_i2c_bus(i2c::I2CBus *bus) { this->light_sensor_.set_bus(bus); }
#endif
  void set_illuminance(sensor::Sensor *value) { this->illuminance_sensor_ = value; }
#ifdef USE_FP2_ORIENTATION
  void set_orientation_i2c_bus(i2c::I2CBus *bus) { this->orientation_sensor_.set_bus(bus); }
#ifdef USE_ESP32
  void set_orientation_native_i2c(i2c::InternalI2CBus *bus, uint32_t frequency) {
    this->orientation_sensor_.set_native_bus(bus, frequency);
  }
#endif
#endif
  void set_enable_native_snapshot(bool value) { this->enable_native_snapshot_ = value; }
  void set_enable_target_reports(bool value) { this->enable_target_reports_ = value; }
  void set_enable_target_events(bool value) { this->enable_target_events_ = value; }
  void set_zone_grid(uint8_t id, const std::vector<uint8_t> &grid);
  enum class ConfigurationState { IDLE, QUEUED, SENT, ACKNOWLEDGED, REJECTED, UNCONFIRMED };
  void set_allow_configuration(bool value) { this->allow_configuration_ = value; }
  bool read_configuration(uint32_t attribute, uint32_t zone);
  void set_radar_configuration(text_sensor::TextSensor *value) {
    this->radar_configuration_sensor_ = value;
    if (value != nullptr) value->publish_state("unknown");
  }
  bool start_learning(uint32_t attribute);
  void set_learning_status(text_sensor::TextSensor *value) { this->learning_status_sensor_ = value; this->publish_learning_(); }
  void set_auto_edge_candidate(text_sensor::TextSensor *value) { this->auto_edge_candidate_sensor_ = value; this->publish_learning_(); }
  const ::fp2_wire::Learning::State &learning_state() const { return this->learning_.state(); }
  bool configure_native_zone(uint32_t id, const std::vector<uint8_t> &map);
  bool configure_special_map(uint32_t id, const std::vector<uint8_t> &map);
  bool configure_scalar(uint32_t id, uint32_t value);
  bool configure_zone_property(uint32_t id, uint32_t zone, uint32_t value);
  // ACK means a strict same-attribute op3/status response, never observed or
  // saved configuration. Stock sequences do not universally echo requests;
  // same-attribute delayed ACKs remain ambiguous. UNCONFIRMED means unknown
  // outcome after a local2s deadline. Commands are never retried automatically.
  ConfigurationState configuration_state() const { return this->configuration_state_; }
  const ::fp2_wire::TargetSnapshot &targets() const { return this->target_zones_.latest_snapshot(); }
  bool targets_known() const { return this->target_zones_.snapshot_known(); }
  void set_allow_tx(bool value) { this->allow_tx_ = value; }
  void set_stale_timeout(uint32_t value) { this->stale_timeout_ms_ = value; }
  void set_query_interval(uint32_t value) { this->query_interval_ms_ = value; }
  void set_presence(binary_sensor::BinarySensor *value) { this->presence_sensor_ = value; }
  void add_native_zone(uint8_t id, binary_sensor::BinarySensor *value) {
    if (id >= 1 && id <= 30) this->native_zone_sensors_[id - 1] = value;
  }
  void set_configuration_status(text_sensor::TextSensor *value) {
    this->configuration_status_sensor_ = value;
    this->set_configuration_state_(this->configuration_state_);
  }
  void add_zone(uint8_t id, binary_sensor::BinarySensor *value) { this->zone_sensors_[id - 1] = value; }
  void setup() override;
  void loop() override;
  void dump_config() override;
  void set_received_valid_frames(sensor::Sensor *value) { this->valid_sensor_ = value; }
  void set_rejected_frames(sensor::Sensor *value) { this->rejected_sensor_ = value; }
  void set_bytes_received(sensor::Sensor *value) { this->bytes_sensor_ = value; }
  void set_last_report(text_sensor::TextSensor *value) { this->report_sensor_ = value; }
  void set_radar_traffic(binary_sensor::BinarySensor *value) { this->traffic_sensor_ = value; }

 protected:
  void publish_targets_(const ::fp2_wire::Frame &frame);
  void set_configuration_state_(ConfigurationState state);
  text_sensor::TextSensor *configuration_status_sensor_{nullptr};
  bool send_configuration_read_(uint32_t now);
  void finish_configuration_read_(bool success, uint32_t now);
  ::fp2_wire::ConfigurationReader configuration_reader_;
  ::fp2_wire::Frame configuration_read_frame_;
  uint32_t configuration_read_attribute_{0}, configuration_read_zone_{0};
  uint32_t configuration_read_retry_at_{0};
  uint8_t configuration_read_attempts_{0};
  bool configuration_read_waiting_{false};
  bool configuration_read_active_{false};
  bool configuration_read_sending_{false};
  text_sensor::TextSensor *radar_configuration_sensor_{nullptr};
  bool learning_busy_() const;
  void publish_learning_();
  ::fp2_wire::Learning learning_;
  bool learning_request_dispatched_{false};
  text_sensor::TextSensor *learning_status_sensor_{nullptr};
  text_sensor::TextSensor *auto_edge_candidate_sensor_{nullptr};
  void mark_transport_unhealthy_(uint32_t now);
  bool transport_unhealthy_{false};
  void log_native_snapshot_();
  void restart_native_snapshot_(uint32_t now);
  bool send_native_snapshot_(uint32_t now);
  bool enable_native_snapshot_{false};
  ::fp2_wire::NativeSnapshotReader native_snapshot_reader_;
  ::fp2_wire::Frame native_snapshot_frame_;
  bool native_snapshot_active_{false};
  bool native_snapshot_restart_{true};
  bool native_snapshot_sending_{false};
  uint8_t native_snapshot_attempts_{0};
  uint32_t native_snapshot_retry_at_{0};
  bool queue_configuration_(::fp2_wire::Frame frame);
  bool allow_configuration_{false};
  ConfigurationState configuration_state_{ConfigurationState::IDLE};
  ::fp2_wire::Frame configuration_frame_;
  uint32_t configuration_sent_at_{0};
  void sync_occupancy_();
  void process_tx_(uint32_t now);
  void send_auxiliary_(uint32_t now);
  bool send_orientation_(uint8_t sequence, uint16_t attribute, uint32_t now, uint8_t operation = 4);
  bool send_frame_(uint8_t sequence, uint8_t operation, const uint8_t *payload, size_t size);
  struct ReverseQuery { uint8_t sequence; uint16_t attribute; uint32_t received_at; };
  std::deque<ReverseQuery> pending_reverse_;
  OrientationSensor orientation_sensor_;
  LightSensor light_sensor_;
  sensor::Sensor *illuminance_sensor_{nullptr};
  sensor::Sensor *target_count_sensor_{nullptr};
  sensor::Sensor *measured_tilt_sensor_{nullptr};
  sensor::Sensor *mounting_direction_sensor_{nullptr};
  sensor::Sensor *orientation_failures_sensor_{nullptr};
  bool enable_orientation_{false};
  bool orientation_was_ready_{false};
  bool startup_angle_sent_{false};
  bool startup_direction_sent_{false};
  uint16_t published_tilt_{0};
  uint8_t published_direction_{0};
  struct Ack { uint8_t sequence; uint16_t attribute; };
  std::deque<Ack> pending_acks_;
  ::fp2_wire::Occupancy occupancy_;
  ::fp2_wire::TargetZones target_zones_;
  std::array<bool, 30> host_zone_{};
  bool enable_target_reports_{false};
  uint32_t target_event_attempts_{0};
  uint32_t target_wire_frames_{0};
  bool enable_target_events_{false};
  bool target_enable_sent_{false};
  uint32_t last_target_enable_at_{0};
  uint32_t last_target_at_{0};
  uint32_t last_tracking_at_{0};
  uint32_t stale_timeout_ms_{90000};
  uint32_t last_health_at_{0};
  binary_sensor::BinarySensor *presence_sensor_{nullptr};
  std::array<binary_sensor::BinarySensor *, 30> zone_sensors_{};
  std::array<binary_sensor::BinarySensor *, 30> native_zone_sensors_{};
  bool allow_tx_{false};
  uint8_t query_sequence_{0};
  uint32_t query_interval_ms_{10000};
  uint32_t last_query_at_{0};
  uint32_t last_tx_at_{0};
  ::fp2_wire::Parser parser_;
  sensor::Sensor *valid_sensor_{nullptr};
  sensor::Sensor *rejected_sensor_{nullptr};
  sensor::Sensor *bytes_sensor_{nullptr};
  text_sensor::TextSensor *report_sensor_{nullptr};
  binary_sensor::BinarySensor *traffic_sensor_{nullptr};
  uint32_t bytes_received_{0};
  uint32_t started_at_{0};
  uint32_t last_publish_at_{0};
  uint32_t last_diagnostics_at_{0};
  uint32_t diagnostic_interval_ms_{1000};
  uint32_t last_valid_at_{0};
  bool seen_valid_{false};
  bool report_pending_{false};
  char report_[96]{};
};

}  // namespace esphome::fp2_poc
