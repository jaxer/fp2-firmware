#include "fp2.h"

#include <cstdio>
#include <cmath>
#include <algorithm>
#include <utility>
#include "esphome/core/hal.h"
#include "esphome/core/application.h"
#include "esphome/core/log.h"
#ifdef USE_ESP32
#include "esp_ota_ops.h"
#include "esp_system.h"
#endif

namespace esphome::fp2 {

static const char *const TAG = "fp2";
static constexpr size_t READ_BUDGET = 512;
static constexpr uint32_t PUBLISH_INTERVAL_MS = 1000;
static constexpr uint32_t TRAFFIC_TIMEOUT_MS = 30000;

void FP2Component::publish_targets_(const ::fp2_wire::Frame &frame) {
#ifdef USE_FP2_TARGET_EVENTS
  if (!this->enable_target_events_ || !this->enable_target_reports_) return;
  // Called only when the shared strict decoder accepted this actual0117 frame.
  // Preserve its entire typed payload, including all raw14-byte records andN0.
  static constexpr char HEX[] = "0123456789abcdef";
  std::string encoded;
  encoded.reserve(frame.payload.size() * 2);
  for (uint8_t byte : frame.payload) {
    encoded.push_back(HEX[byte >> 4]);
    encoded.push_back(HEX[byte & 15]);
  }
  ++this->target_event_attempts_;
  this->fire_homeassistant_event("esphome.fp2_targets", {
      {"node", std::string(App.get_name().c_str())}, {"source", "radar_uart"},
      {"sequence", std::to_string(frame.sequence)}, {"payload_hex", encoded},
      {"count", std::to_string(this->target_zones_.latest_snapshot().targets.size())}});
#else
  (void) frame;
#endif
}

void FP2Component::setup() {
  this->started_at_ = millis();
  this->last_publish_at_ = this->started_at_;
  this->last_diagnostics_at_ = this->started_at_;
  this->last_health_at_ = this->started_at_;
  this->last_tx_at_ = this->started_at_ - 50;
  this->last_query_at_ = this->started_at_ - this->query_interval_ms_;
  // No GPIO or radar initialization, or initial presence state.
  this->occupancy_.invalidate();
  this->startup_angle_sent_ = false;
  this->startup_direction_sent_ = false;
  if (this->enable_orientation_)
    this->orientation_sensor_.setup();
  if (this->illuminance_sensor_ != nullptr)
    this->light_sensor_.setup();
  this->sync_occupancy_();
}

void FP2Component::loop() {
  const uint32_t sensor_now = millis();
  if (sensor_now - this->last_health_at_ >= this->stale_timeout_ms_)
    this->mark_transport_unhealthy_(sensor_now);
  if (this->illuminance_sensor_ != nullptr)
    this->light_sensor_.loop(sensor_now);
  if (this->enable_orientation_) {
    this->orientation_sensor_.loop(sensor_now);
    const bool ready = this->orientation_sensor_.angle_ready(sensor_now) &&
                       this->orientation_sensor_.orientation_ready(sensor_now);
    if (ready != this->orientation_was_ready_)
      this->restart_native_snapshot_(sensor_now);
    if (!ready || ready != this->orientation_was_ready_) {
      this->occupancy_.invalidate();
      this->target_zones_.invalidate();
      this->sync_occupancy_();
      if (ready)
        this->last_query_at_ = sensor_now - this->query_interval_ms_;
    }
    this->orientation_was_ready_ = ready;
  }
  ::fp2_wire::Frame frame;
  for (size_t count = 0; count < READ_BUDGET && this->available() > 0; count++) {
    uint8_t byte;
    if (!this->read_byte(&byte))
      break;
    this->bytes_received_++;
    const uint32_t rejected_before = this->parser_.rejected_frames();
    const bool complete = this->parser_.feed(byte, frame);
    if (this->parser_.rejected_frames() != rejected_before) {
      if (this->configuration_read_active_) this->finish_configuration_read_(false, millis());
      this->mark_transport_unhealthy_(millis());
      this->occupancy_.invalidate();
      this->target_zones_.invalidate();
      this->sync_occupancy_();
    }
    if (!complete)
      continue;
    this->last_valid_at_ = millis();
    this->seen_valid_ = true;
    if (frame.payload.size() >= 2 && frame.payload[0] == 1 && frame.payload[1] == 0x17)
      ++this->target_wire_frames_;
    // Private monitor replies never become Last report data or report ACKs.
    const auto &private_payload = frame.payload;
    const bool private_raw = frame.operation == 4 && private_payload.size() >= 7 &&
        private_payload[0] == 1 && private_payload[1] == 2 && private_payload[2] == 5 &&
        private_payload[5] == 3 && private_payload[6] == 'M';
    if (private_raw) {
      if (this->configuration_read_active_) {
        if (this->configuration_read_waiting_) continue;
        if (this->configuration_reader_.ingest(frame, this->last_valid_at_)) {
          if (this->configuration_reader_.complete())
            this->finish_configuration_read_(true, this->last_valid_at_);
          else if (this->configuration_reader_.failed())
            this->finish_configuration_read_(false, this->last_valid_at_);
        }
        continue;
      }
      if (!this->transport_unhealthy_ && this->enable_native_snapshot_ && this->native_snapshot_active_ &&
          !this->native_snapshot_restart_ &&
          this->native_snapshot_reader_.ingest(frame, this->last_valid_at_) &&
          this->native_snapshot_reader_.complete()) {
        this->occupancy_.seed_native_cache(this->native_snapshot_reader_.snapshot(), this->last_valid_at_);
        this->native_snapshot_active_ = false;
        this->log_native_snapshot_();
        this->sync_occupancy_();
      }
      continue;
    }
    if (this->enable_orientation_ && frame.operation == 1 && frame.payload.size() == 2) {
      const uint16_t requested = (uint16_t(frame.payload[0]) << 8) | frame.payload[1];
      if (requested == 0x0120 || requested == 0x0143) {
        bool duplicate = false;
        for (const auto &query : this->pending_reverse_)
          duplicate |= query.sequence == frame.sequence && query.attribute == requested;
        if (!duplicate && this->pending_reverse_.size() < 16)
          this->pending_reverse_.push_back({frame.sequence, requested, this->last_valid_at_});
      }
    }
    if (this->configuration_state_ == ConfigurationState::SENT && frame.operation == 3 &&
        frame.payload.size() == 4 && frame.payload[2] == 0 &&
        frame.payload[0] == this->configuration_frame_.payload[0] &&
        frame.payload[1] == this->configuration_frame_.payload[1]) {
      if (this->last_valid_at_ - this->configuration_sent_at_ >= 2000)
        this->set_configuration_state_(ConfigurationState::UNCONFIRMED);
      else
        this->set_configuration_state_(frame.payload[3] == 0 ? ConfigurationState::ACKNOWLEDGED
                                                               : ConfigurationState::REJECTED);
    }
    const bool learning_observed = this->learning_request_dispatched_ && this->learning_.observe(frame);
    const bool learning_candidate = learning_observed && frame.operation == 5 &&
        frame.payload.size() == 45 && frame.payload[0] == 1 && frame.payload[1] == 0x49;
    if (learning_observed) {
      this->publish_learning_();
      if (frame.operation == 5) this->restart_native_snapshot_(this->last_valid_at_);
    }
    const bool occupancy_report = this->occupancy_.ingest(frame, this->last_valid_at_);
    const uint32_t target_revision = this->target_zones_.snapshot_revision();
    const bool model_target_report = this->target_zones_.ingest(frame, this->last_valid_at_);
    uint16_t attribute = 0;
    uint8_t type;
    uint32_t value;
    const bool scalar = ::fp2_wire::decode_scalar(frame, attribute, type, value);
    const bool report = frame.operation == 4 || frame.operation == 5;
    const bool target_snapshot = this->target_zones_.snapshot_revision() != target_revision;
    if (target_snapshot) {
      this->last_tracking_at_ = this->last_valid_at_;
      if (model_target_report) this->last_target_at_ = this->last_valid_at_;
      attribute = 0x0117;
      this->publish_targets_(frame);
    }
    if (learning_candidate) attribute = 0x0149;
    const bool occupancy_attribute = attribute == 0x0104 || attribute == 0x0142;
    if (report && (learning_candidate || target_snapshot || (scalar && (!occupancy_attribute || occupancy_report)))) {
      // Room snapshots supervise transport health; zone events do not expire individually.
      if (occupancy_report && attribute == 0x0104) {
        this->last_health_at_ = this->last_valid_at_;
        if (this->transport_unhealthy_) {
          this->transport_unhealthy_ = false;
          this->restart_native_snapshot_(this->last_valid_at_);
        }
      }
      if (this->allow_tx_ && this->pending_acks_.size() < 16)
        this->pending_acks_.push_back({frame.sequence, attribute});
    }
    if (this->last_valid_at_ - this->last_health_at_ >= this->stale_timeout_ms_)
      this->target_zones_.invalidate();
    this->sync_occupancy_();
    if (scalar) {
      std::snprintf(this->report_, sizeof(this->report_), "id=0x%04X type=0x%02X value=%lu",
                    static_cast<unsigned>(attribute), static_cast<unsigned>(type),
                    static_cast<unsigned long>(value));
    } else {
      // Never expose variable-length zone, calibration, or arbitrary payload data.
      std::snprintf(this->report_, sizeof(this->report_), "op=0x%02X bytes=%u",
                    static_cast<unsigned>(frame.operation), static_cast<unsigned>(frame.payload.size()));
    }
    this->report_pending_ = true;
  }

  const uint32_t now = millis();
  if (now - this->last_health_at_ >= this->stale_timeout_ms_) {
    this->mark_transport_unhealthy_(now);
    this->occupancy_.invalidate();
    this->target_zones_.invalidate();
    this->sync_occupancy_();
  }
  if (this->occupancy_.room().known && this->occupancy_.room().occupied) {
    if (now - this->last_tracking_at_ >= 5000)
      this->target_zones_.invalidate();
    else if (now - this->last_target_at_ >= 5000)
      this->target_zones_.invalidate_geometry();
    this->sync_occupancy_();
  }
  this->process_tx_(now);
  if (now - this->last_publish_at_ < PUBLISH_INTERVAL_MS)
    return;
  this->last_publish_at_ = now;
  if (this->illuminance_sensor_ != nullptr) {
    if (this->light_sensor_.ready(now))
      this->illuminance_sensor_->publish_state(this->light_sensor_.lux());
    else if (this->illuminance_sensor_->has_state())
      this->illuminance_sensor_->publish_state(NAN);
  }
  // Secondary exports only; fast UART, occupancy, targets and health run above.
  if (now - this->last_diagnostics_at_ >= this->diagnostic_interval_ms_) {
    this->last_diagnostics_at_ = now;
    if (this->measured_tilt_sensor_ != nullptr)
      this->measured_tilt_sensor_->publish_state(this->orientation_sensor_.angle_ready(now) ? float(this->orientation_sensor_.tilt()) : NAN);
    if (this->mounting_direction_sensor_ != nullptr)
      this->mounting_direction_sensor_->publish_state(this->orientation_sensor_.orientation_ready(now) ? float(this->orientation_sensor_.direction()) : NAN);
    if (this->orientation_failures_sensor_ != nullptr)
      this->orientation_failures_sensor_->publish_state(this->orientation_sensor_.read_failures());
    if (this->valid_sensor_ != nullptr)
      this->valid_sensor_->publish_state(this->parser_.good_frames());
    if (this->rejected_sensor_ != nullptr)
      this->rejected_sensor_->publish_state(this->parser_.rejected_frames());
    if (this->bytes_sensor_ != nullptr)
      this->bytes_sensor_->publish_state(this->bytes_received_);
    if (this->report_sensor_ != nullptr && this->report_pending_) {
      this->report_sensor_->publish_state(this->report_);
      this->report_pending_ = false;
    }
  }
  if (this->traffic_sensor_ != nullptr &&
      (this->seen_valid_ || now - this->started_at_ >= TRAFFIC_TIMEOUT_MS)) {
    this->traffic_sensor_->publish_state(this->seen_valid_ && now - this->last_valid_at_ < TRAFFIC_TIMEOUT_MS);
  }
}

void FP2Component::dump_config() {
#ifdef USE_ESP32
  const auto *running = esp_ota_get_running_partition();
  const auto *selected = esp_ota_get_boot_partition();
  ESP_LOGI(TAG, "Boot partition: running=0x%06lx selected=0x%06lx reset_reason=%u",
           static_cast<unsigned long>(running ? running->address : 0),
           static_cast<unsigned long>(selected ? selected->address : 0),
           static_cast<unsigned>(esp_reset_reason()));
#endif
  const uint32_t target_packets = this->target_zones_.snapshot_revision();
  if (target_packets != 0) {
    ESP_LOGI(TAG, "Tracking telemetry: wire=%lu decoded=%lu send_attempts=%lu known=%s count=%u age_ms=%lu",
             static_cast<unsigned long>(this->target_wire_frames_), static_cast<unsigned long>(target_packets), static_cast<unsigned long>(this->target_event_attempts_),
             this->target_zones_.snapshot_known() ? "yes" : "no",
             static_cast<unsigned>(this->target_zones_.latest_snapshot().targets.size()),
             static_cast<unsigned long>(millis() - this->last_tracking_at_));
  } else {
    ESP_LOGI(TAG, "Tracking telemetry: wire=%lu decoded=0 send_attempts=%lu known=no count=unknown age_ms=unknown",
             static_cast<unsigned long>(this->target_wire_frames_), static_cast<unsigned long>(this->target_event_attempts_));
  }
  if (this->illuminance_sensor_ != nullptr) {
    ESP_LOGI(TAG, "Light sensor: status=%s, successful_reads=%lu, failed_reads=%lu, ready=%s, lux=%lu",
             this->light_sensor_.status(), static_cast<unsigned long>(this->light_sensor_.successful_reads()),
             static_cast<unsigned long>(this->light_sensor_.read_failures()),
             this->light_sensor_.ready(millis()) ? "yes" : "no",
             static_cast<unsigned long>(this->light_sensor_.lux()));
    LOG_SENSOR("  ", "Illuminance", this->illuminance_sensor_);
  }
  if (this->enable_orientation_) {
    const uint32_t now = millis();
    this->orientation_sensor_.dump_config();
    ESP_LOGI(TAG, "Orientation I2C: failed_reads=%lu, completed_batches=%lu, last_failed_register=0x%02X, last_error=%u, native_error=0x%08lX",
             static_cast<unsigned long>(this->orientation_sensor_.read_failures()),
             static_cast<unsigned long>(this->orientation_sensor_.sample_batches()),
             this->orientation_sensor_.failed_register(), this->orientation_sensor_.last_read_error(),
             static_cast<unsigned long>(this->orientation_sensor_.last_native_error()));
    const bool angle = this->orientation_sensor_.angle_ready(now);
    const bool direction = this->orientation_sensor_.orientation_ready(now);
    if (angle && direction)
      ESP_LOGI(TAG, "Measured orientation ready: tilt=%u, direction=%u",
               static_cast<unsigned>(this->orientation_sensor_.tilt()),
               static_cast<unsigned>(this->orientation_sensor_.direction()));
    else
      ESP_LOGI(TAG, "Measured orientation pending: status=%s, angle=%s, direction=%s", this->orientation_sensor_.status(), angle ? "ready" : "unknown",
               direction ? "ready" : "unknown");
  }
  this->log_native_snapshot_();
  ESP_LOGCONFIG(TAG, "Pinned-monitor native bootstrap: %s", this->enable_native_snapshot_ ? "enabled" : "disabled");
  ESP_LOGCONFIG(TAG, "Normal configuration commands: %s", this->allow_configuration_ ? "enabled" : "disabled");
  ESP_LOGCONFIG(TAG, "FP2 occupancy diagnostics; allowlisted TX: %s", this->allow_tx_ ? "enabled" : "disabled");
  LOG_BINARY_SENSOR("  ", "Room presence", this->presence_sensor_);
  for (size_t i = 0; i < this->zone_sensors_.size(); i++) {
    if (this->zone_sensors_[i] != nullptr) {
      ESP_LOGCONFIG(TAG, "  Configured zone ID: %u (%s)", static_cast<unsigned>(i + 1),
                    this->host_zone_[i] ? "host grid" : "native event");
      LOG_BINARY_SENSOR("    ", "Zone presence", this->zone_sensors_[i]);
    }
  }
  LOG_SENSOR("  ", "Valid frames", this->valid_sensor_);
  LOG_SENSOR("  ", "Rejected frames", this->rejected_sensor_);
  LOG_SENSOR("  ", "Bytes received", this->bytes_sensor_);
  LOG_TEXT_SENSOR("  ", "Last report", this->report_sensor_);
  LOG_BINARY_SENSOR("  ", "Radar traffic", this->traffic_sensor_);
}

void FP2Component::set_zone_grid(uint8_t id, const std::vector<uint8_t> &grid) {
  if (id < 1 || id > 30 || grid.size() != 40)
    return;
  std::array<uint8_t, 40> bitmap{};
  for (size_t i = 0; i < bitmap.size(); i++)
    bitmap[i] = grid[i];
  this->host_zone_[id - 1] = this->target_zones_.configure(id, bitmap);
}

void FP2Component::sync_occupancy_() {
  const uint32_t now = millis();
  const bool orientation_ready = !this->enable_orientation_ ||
      (this->orientation_sensor_.angle_ready(now) && this->orientation_sensor_.orientation_ready(now));
  auto sync = [orientation_ready](binary_sensor::BinarySensor *sensor, const ::fp2_wire::OccupancyState &state) {
    if (sensor == nullptr)
      return;
    if (!orientation_ready || !state.known) {
      if (sensor->has_state())
        sensor->invalidate_state();
    } else if (!sensor->has_state() || sensor->state != state.occupied) {
      sensor->publish_state(state.occupied);
    }
  };
  sync(this->presence_sensor_, this->occupancy_.room());
  if (this->target_count_sensor_ != nullptr) {
    float count = NAN;
    const auto &room = this->occupancy_.room();
    if (orientation_ready && room.known) {
      // Authoritative vacancy means zero; stale tracking while occupied means unknown.
      if (!room.occupied) count = 0;
      else if (this->target_zones_.snapshot_known() && now - this->last_tracking_at_ < 5000)
        count = this->target_zones_.latest_snapshot().targets.size();
    }
    const float previous = this->target_count_sensor_->state;
    if (!this->target_count_sensor_->has_state() ||
        !(previous == count || (std::isnan(previous) && std::isnan(count))))
      this->target_count_sensor_->publish_state(count);
  }
  for (uint8_t id = 1; id <= 30; id++) {
    sync(this->zone_sensors_[id - 1], this->host_zone_[id - 1] ? this->target_zones_.zone(id)
                                                            : this->occupancy_.zone(id));
    sync(this->native_zone_sensors_[id - 1], this->occupancy_.zone(id));
  }
}

void FP2Component::set_configuration_state_(ConfigurationState state) {
  this->configuration_state_ = state;
  if (this->configuration_status_sensor_ == nullptr) return;
  const char *label = "idle";
  switch (state) {
    case ConfigurationState::IDLE: break;
    case ConfigurationState::QUEUED: label = "queued"; break;
    case ConfigurationState::SENT: label = "sent"; break;
    case ConfigurationState::ACKNOWLEDGED: label = "acknowledged (not verified/saved)"; break;
    case ConfigurationState::REJECTED: label = "rejected"; break;
    case ConfigurationState::UNCONFIRMED: label = "unconfirmed (unknown outcome)"; break;
  }
  this->configuration_status_sensor_->publish_state(label);
}

bool FP2Component::queue_configuration_(::fp2_wire::Frame frame) {
  if (!this->allow_tx_ || !this->allow_configuration_ || this->learning_busy_() || this->configuration_read_active_ ||
      this->configuration_state_ == ConfigurationState::QUEUED ||
      this->configuration_state_ == ConfigurationState::SENT) return false;
  this->restart_native_snapshot_(millis());
  this->configuration_frame_ = std::move(frame);
  this->set_configuration_state_(ConfigurationState::QUEUED);
  const auto &payload = this->configuration_frame_.payload;
  if (payload[0] == 1 && payload[1] == 0x14)
    this->occupancy_.invalidate_zone(payload[5]);
  else
    this->occupancy_.invalidate_zones();
  // Native setters can clear cached0142 state without a replacement report.
  // Acceptance invalidates old observations; neither the queue nor an ACK
  // claims the requested geometry is applied, saved, or vacant. Host grids
  // and the actual room observation remain independent.
  this->sync_occupancy_();
  return true;
}

bool FP2Component::read_configuration(uint32_t attribute, uint32_t zone) {
  if (!this->allow_tx_ || this->configuration_read_active_ || this->learning_busy_() ||
      this->configuration_state_ == ConfigurationState::QUEUED ||
      this->configuration_state_ == ConfigurationState::SENT) return false;
  ::fp2_wire::ConfigurationReader next;
  bool valid = false;
  if (attribute == 0x0114) valid = next.start_zone(zone, millis());
  else if (zone == 0) valid = next.start_scalar(attribute, millis()) || next.start_special_map(attribute, millis());
  if (!valid) return false;
  this->restart_native_snapshot_(millis());
  this->configuration_reader_ = std::move(next);
  this->configuration_read_attribute_ = attribute;
  this->configuration_read_zone_ = zone;
  this->configuration_read_attempts_ = 1;
  this->configuration_read_waiting_ = false;
  this->configuration_read_active_ = true;
  if (this->radar_configuration_sensor_ != nullptr) this->radar_configuration_sensor_->publish_state("reading");
  return true;
}

void FP2Component::finish_configuration_read_(bool success, uint32_t now) {
  if (!success) {
    if (this->configuration_read_waiting_) return;
    const auto &failed = this->configuration_reader_.result();
    ESP_LOGW(TAG, "Configuration read: failed attempt=%u requests=%lu elapsed_ms=%lu",
             unsigned(this->configuration_read_attempts_), static_cast<unsigned long>(failed.requests),
             static_cast<unsigned long>(now-failed.started_at));
    if (this->configuration_read_attempts_ < 2) {
      // Keep exclusive ownership while waiting. Discard the entire old proof;
      // retry only this read-only getter from its pinned prefix/instance gates.
      this->configuration_reader_ = ::fp2_wire::ConfigurationReader{};
      this->configuration_read_waiting_ = true;
      this->configuration_read_retry_at_ = now + 250;
      return;
    }
  }
  this->configuration_read_waiting_ = false;
  this->configuration_read_active_ = false;
  if (this->radar_configuration_sensor_ != nullptr) {
    if (!success) {
      this->radar_configuration_sensor_->publish_state("read_failed (no result)");
    } else {
      const auto &result = this->configuration_reader_.result();
      static constexpr char hex[] = "0123456789abcdef";
      char mask[81];
      for (size_t i = 0; i < result.mask.size(); ++i) {
        mask[2*i] = hex[result.mask[i] >> 4]; mask[2*i+1] = hex[result.mask[i] & 15];
      }
      mask[80] = 0;
      char text[255];
      int length;
      if (result.kind == ::fp2_wire::ConfigurationReader::Kind::ZONE) {
        length = std::snprintf(text, sizeof(text),
            "{\"kind\":\"zone\",\"id\":%u,\"active_raw\":%u,\"sensitivity\":%u,\"type\":%u,\"close_away_raw\":%u,\"mask\":\"%s\",\"source\":\"radar_ram\",\"observed_ms\":%lu}",
            unsigned(result.zone_id), unsigned(result.active_byte), unsigned(result.sensitivity),
            unsigned(result.type), unsigned(result.close_away), mask, static_cast<unsigned long>(result.completed_at));
      } else if (result.kind == ::fp2_wire::ConfigurationReader::Kind::SPECIAL_MAP) {
        length = std::snprintf(text, sizeof(text),
            "{\"kind\":\"map\",\"attribute\":%u,\"mask\":\"%s\",\"source\":\"radar_ram\",\"observed_ms\":%lu}", unsigned(result.attribute), mask, static_cast<unsigned long>(result.completed_at));
      } else {
        length = std::snprintf(text, sizeof(text),
            "{\"kind\":\"scalar\",\"attribute\":%u,\"raw\":%lu,\"wire\":%lld,\"source\":\"radar_ram\",\"observed_ms\":%lu}",
            unsigned(result.attribute), static_cast<unsigned long>(result.raw_value), static_cast<long long>(result.wire_value), static_cast<unsigned long>(result.completed_at));
      }
      if (length > 0 && size_t(length) < sizeof(text)) this->radar_configuration_sensor_->publish_state(text);
      else this->radar_configuration_sensor_->publish_state("read_failed (result length)");
    }
  }
  // Readback does not invalidate observed occupancy. Resume an independent,
  // fresh bootstrap proof rather than routing a getter reply to that reader.
  this->restart_native_snapshot_(now);
}

bool FP2Component::send_configuration_read_(uint32_t now) {
  if (!this->configuration_read_active_) return false;
  if (this->configuration_read_waiting_) {
    if (int32_t(now-this->configuration_read_retry_at_) < 0) return false;
    this->configuration_read_waiting_ = false;
    ++this->configuration_read_attempts_;
    ::fp2_wire::ConfigurationReader next;
    const bool valid = this->configuration_read_attribute_ == 0x0114 ?
        next.start_zone(this->configuration_read_zone_, now) :
        (next.start_scalar(this->configuration_read_attribute_, now) ||
         next.start_special_map(this->configuration_read_attribute_, now));
    if (!valid) { this->finish_configuration_read_(false, now); return false; }
    this->configuration_reader_ = std::move(next);
  }
  if (!this->configuration_reader_.next_request(now, this->query_sequence_, this->configuration_read_frame_)) {
    if (this->configuration_reader_.failed()) this->finish_configuration_read_(false, now);
    return false;
  }
  ++this->query_sequence_;
  this->configuration_read_sending_ = true;
  const auto &request = this->configuration_read_frame_;
  this->send_frame_(request.sequence, request.operation, request.payload.data(), request.payload.size());
  this->configuration_read_sending_ = false;
  return true;
}

bool FP2Component::learning_busy_() const {
  const auto status = this->learning_.state().status;
  return status == ::fp2_wire::Learning::Status::AWAITING_COMPLETION ||
         status == ::fp2_wire::Learning::Status::OUTCOME_UNKNOWN;
}

void FP2Component::publish_learning_() {
  const auto &state = this->learning_.state();
  const char *status = "unknown";
  switch (state.status) {
    case ::fp2_wire::Learning::Status::UNKNOWN: break;
    case ::fp2_wire::Learning::Status::AWAITING_COMPLETION: status = "awaiting completion"; break;
    case ::fp2_wire::Learning::Status::COMPLETED: status = "completed (not persistence proof)"; break;
    case ::fp2_wire::Learning::Status::OUTCOME_UNKNOWN: status = "outcome unknown (no retry/cancel)"; break;
  }
  const char *action = state.action == ::fp2_wire::Learning::Action::BACKGROUND ? "background" :
                       state.action == ::fp2_wire::Learning::Action::AUTO_EDGE ? "auto edge" : "none";
  if (this->learning_status_sensor_ != nullptr) {
    char text[160];
    std::snprintf(text, sizeof(text), "%s: %s; ack=%s", action, status,
                  state.acknowledged ? "received (not completion)" : state.ack_failed ? "error" : "unconfirmed");
    this->learning_status_sensor_->publish_state(text);
  }
  if (this->auto_edge_candidate_sensor_ != nullptr) {
    if (!state.candidate_available) {
      this->auto_edge_candidate_sensor_->publish_state("unknown");
    } else {
      static constexpr char hex[] = "0123456789abcdef";
      char text[81];
      for (size_t i = 0; i < state.candidate.size(); ++i) {
        text[2*i] = hex[state.candidate[i] >> 4];
        text[2*i+1] = hex[state.candidate[i] & 15];
      }
      text[80] = 0;
      this->auto_edge_candidate_sensor_->publish_state(text);
    }
  }
}

bool FP2Component::start_learning(uint32_t attribute) {
  ::fp2_wire::Learning::Action action;
  if (attribute == 0x0113) action = ::fp2_wire::Learning::Action::BACKGROUND;
  else if (attribute == 0x0150) action = ::fp2_wire::Learning::Action::AUTO_EDGE;
  else return false;
  // Stage domain changes locally: a busy or opted-out queue never changes the
  // actual learning state. There is no automatic start, cancel, apply or retry.
  auto next = this->learning_;
  ::fp2_wire::Frame request;
  if (!next.start(action, 0, millis(), 120000, request) ||
      !this->queue_configuration_(std::move(request))) return false;
  this->learning_ = std::move(next);
  this->learning_request_dispatched_ = false;
  this->publish_learning_();
  return true;
}

bool FP2Component::configure_native_zone(uint32_t id, const std::vector<uint8_t> &map) {
  ::fp2_wire::Frame frame;
  return ::fp2_commands::zone_geometry(0, id, map.data(), map.size(), frame) &&
         this->queue_configuration_(std::move(frame));
}
bool FP2Component::configure_special_map(uint32_t id, const std::vector<uint8_t> &map) {
  ::fp2_wire::Frame frame;
  return ::fp2_commands::special_map(0, id, map.data(), map.size(), frame) &&
         this->queue_configuration_(std::move(frame));
}
bool FP2Component::configure_scalar(uint32_t id, uint32_t value) {
  ::fp2_wire::Frame frame;
  return ::fp2_commands::scalar_control(0, id, value, frame) &&
         this->queue_configuration_(std::move(frame));
}
bool FP2Component::configure_zone_property(uint32_t id, uint32_t zone, uint32_t value) {
  ::fp2_wire::Frame frame;
  return ::fp2_commands::zone_property(0, id, zone, value, frame) &&
         this->queue_configuration_(std::move(frame));
}

void FP2Component::process_tx_(uint32_t now) {
  const auto learning_before = this->learning_.state().status;
  this->learning_.expire(now);
  if (this->learning_.state().status != learning_before) this->publish_learning_();
  if (this->configuration_state_ == ConfigurationState::SENT &&
      now - this->configuration_sent_at_ >= 2000)
    this->set_configuration_state_(ConfigurationState::UNCONFIRMED);
  if (!this->allow_tx_ || now - this->last_tx_at_ < 50)
    return;
  for (auto it = this->pending_reverse_.begin(); it != this->pending_reverse_.end();) {
    if (now - it->received_at > 30000)
      it = this->pending_reverse_.erase(it);
    else
      ++it;
  }
  // An overdue health query wins one send slot even under continuous reports.
  if (now - this->last_query_at_ >= this->query_interval_ms_) {
    const uint8_t payload[] = {0x01, 0x04};
    this->send_frame_(this->query_sequence_++, 1, payload, sizeof(payload));
    this->last_query_at_ = now;
  } else {
    if (this->enable_orientation_) {
      // Actual reverse requests retain priority and their original sequence.
      for (auto it = this->pending_reverse_.begin(); it != this->pending_reverse_.end(); ++it) {
        if (!this->send_orientation_(it->sequence, it->attribute, now))
          continue;
        this->pending_reverse_.erase(it);
        return;
      }
      // The radar may already be running when the ESP boots, so its one-shot
      // angle request may never reach us. Synchronize each fresh value once.
      const uint16_t startup_attributes[] = {0x0120, 0x0143};
      for (const uint16_t attribute : startup_attributes) {
        const bool sent = attribute == 0x0120 ? this->startup_angle_sent_ : this->startup_direction_sent_;
        if (!sent && this->send_orientation_(this->query_sequence_, attribute, now)) {
          this->query_sequence_++;
          return;
        }
      }
      // Stock suppresses tilt deltas within inclusive +/-4 from the last
      // published value. Its timer units are not independently established;
      // use the existing bounded TX slots, without inventing a new timer.
      const int tilt_delta = int(this->orientation_sensor_.tilt()) - int(this->published_tilt_);
      if (this->startup_angle_sent_ && (tilt_delta <= -5 || tilt_delta >= 5) &&
          this->send_orientation_(this->query_sequence_, 0x0120, now, 5)) {
        this->query_sequence_++;
        return;
      }
      if (this->startup_direction_sent_ &&
          this->orientation_sensor_.direction() != this->published_direction_ &&
          this->send_orientation_(this->query_sequence_, 0x0143, now, 5)) {
        this->query_sequence_++;
        return;
      }
    }
    // Unready orientation must not prevent report-enable or ACK service.
    this->send_auxiliary_(now);
    return;
  }
  this->last_tx_at_ = now;
}

bool FP2Component::send_orientation_(uint8_t sequence, uint16_t attribute, uint32_t now, uint8_t operation) {
  const bool angle = attribute == 0x0120;
  if (!(angle ? this->orientation_sensor_.angle_ready(now)
              : this->orientation_sensor_.orientation_ready(now)))
    return false;
  const uint16_t value = angle ? this->orientation_sensor_.tilt() : this->orientation_sensor_.direction();
  const uint8_t payload[] = {static_cast<uint8_t>(attribute >> 8), static_cast<uint8_t>(attribute),
                             static_cast<uint8_t>(angle ? 1 : 0),
                             static_cast<uint8_t>(angle ? value >> 8 : value), static_cast<uint8_t>(value)};
  this->restart_native_snapshot_(now);
  this->send_frame_(sequence, operation, payload, angle ? 5 : 4);
  if (angle) {
    this->startup_angle_sent_ = true;
    this->published_tilt_ = value;
  } else {
    this->startup_direction_sent_ = true;
    this->published_direction_ = static_cast<uint8_t>(value);
  }
  this->last_tx_at_ = now;
  return true;
}

void FP2Component::send_auxiliary_(uint32_t now) {
  if (this->enable_target_reports_ && this->seen_valid_ &&
             (!this->target_enable_sent_ || (now - this->last_target_enable_at_ >= 30000 &&
                                            now - this->last_tracking_at_ >= 10000))) {
    const uint8_t payload[] = {0x01, 0x12, 0x04, 0x01};
    this->send_frame_(this->query_sequence_++, 2, payload, sizeof(payload));
    this->target_enable_sent_ = true;
    this->last_target_enable_at_ = now;
  } else if (!this->pending_acks_.empty()) {
    const Ack ack = this->pending_acks_.front();
    this->pending_acks_.pop_front();
    const uint8_t payload[] = {static_cast<uint8_t>(ack.attribute >> 8),
                               static_cast<uint8_t>(ack.attribute), 0, 0};
    this->send_frame_(ack.sequence, 3, payload, sizeof(payload));
  } else if (this->allow_configuration_ && this->configuration_state_ == ConfigurationState::QUEUED) {
    auto &frame = this->configuration_frame_;
    frame.sequence = this->query_sequence_++;
    if (!this->send_frame_(frame.sequence, frame.operation, frame.payload.data(), frame.payload.size())) return;
    const auto &payload = frame.payload;
    if (payload.size() == 4 && payload[0] == 1 && payload[2] == 4 && payload[3] == 1 &&
        (payload[1] == 0x13 || payload[1] == 0x50))
      this->learning_request_dispatched_ = true;
    this->set_configuration_state_(ConfigurationState::SENT);
    this->configuration_sent_at_ = now;
  } else if (this->send_configuration_read_(now)) {
    // The sole explicit readback client owns monitor replies until terminal.
  } else if (this->send_native_snapshot_(now)) {
    // The read-only bootstrap uses only otherwise-idle send slots.
  } else {
    return;
  }
  this->last_tx_at_ = now;
}

void FP2Component::mark_transport_unhealthy_(uint32_t now) {
  if (this->transport_unhealthy_) return;
  if (this->configuration_read_active_) this->finish_configuration_read_(false, now);
  this->transport_unhealthy_ = true;
  this->restart_native_snapshot_(now);
  // Request an actual0104 health observation in the next paced health slot.
  this->last_query_at_ = now - this->query_interval_ms_;
}

void FP2Component::log_native_snapshot_() {
  const auto &native = this->native_snapshot_reader_.snapshot();
  if (this->native_snapshot_reader_.complete()) {
    ESP_LOGI(TAG, "Native snapshot: enabled=%s complete=yes failed=no attempts=%u requests=%lu counter_delta=%llu",
             this->enable_native_snapshot_ ? "yes" : "no", static_cast<unsigned>(this->native_snapshot_attempts_),
             static_cast<unsigned long>(native.requests),
             static_cast<unsigned long long>(native.counter_final - native.counter_baseline));
  } else {
    ESP_LOGI(TAG, "Native snapshot: enabled=%s complete=no failed=%s attempts=%u requests=%lu counter_delta=unknown",
             this->enable_native_snapshot_ ? "yes" : "no", this->native_snapshot_reader_.failed() ? "yes" : "no",
             static_cast<unsigned>(this->native_snapshot_attempts_), static_cast<unsigned long>(native.requests));
  }
}

void FP2Component::restart_native_snapshot_(uint32_t now) {
  this->native_snapshot_reader_.invalidate(now);
  this->native_snapshot_active_ = false;
  this->native_snapshot_restart_ = true;
  this->native_snapshot_attempts_ = 0;
  this->native_snapshot_retry_at_ = now;
}

bool FP2Component::send_native_snapshot_(uint32_t now) {
  if (!this->enable_native_snapshot_ || this->transport_unhealthy_ || this->learning_busy_() || this->configuration_read_active_ ||
      this->configuration_state_ == ConfigurationState::QUEUED ||
      this->configuration_state_ == ConfigurationState::SENT ||
      (this->enable_orientation_ && (!this->startup_angle_sent_ || !this->startup_direction_sent_ ||
       !this->orientation_sensor_.angle_ready(now) || !this->orientation_sensor_.orientation_ready(now)))) return false;
  if (this->native_snapshot_active_ && this->native_snapshot_reader_.failed()) {
    this->log_native_snapshot_();
    this->native_snapshot_active_ = false;
    this->native_snapshot_restart_ = this->native_snapshot_attempts_ < 3;
    this->native_snapshot_retry_at_ = now + 1000;
  }
  if (this->native_snapshot_restart_) {
    if (this->native_snapshot_attempts_ >= 3 || int32_t(now-this->native_snapshot_retry_at_) < 0) return false;
    this->native_snapshot_reader_.invalidate(now);
    this->native_snapshot_restart_ = false;
    this->native_snapshot_active_ = true;
    ++this->native_snapshot_attempts_;
  }
  if (!this->native_snapshot_active_) return false;
  if (!this->native_snapshot_reader_.next_request(now, this->query_sequence_, this->native_snapshot_frame_)) return false;
  this->query_sequence_++;
  this->native_snapshot_sending_ = true;
  const auto &request = this->native_snapshot_frame_;
  this->send_frame_(request.sequence, request.operation, request.payload.data(), request.payload.size());
  this->native_snapshot_sending_ = false;
  return true;
}

bool FP2Component::send_frame_(uint8_t sequence, uint8_t operation, const uint8_t *payload, size_t size) {
  // Private encoder accepts only the exact bounded wire shapes used above.
  const bool configuration = this->allow_configuration_ &&
      this->configuration_state_ == ConfigurationState::QUEUED && operation == 2 &&
      sequence == this->configuration_frame_.sequence && size <= 46 &&
      size == this->configuration_frame_.payload.size() &&
      std::equal(this->configuration_frame_.payload.begin(), this->configuration_frame_.payload.end(), payload);
  const bool native_read = this->enable_native_snapshot_ && this->native_snapshot_sending_ &&
      this->native_snapshot_active_ && operation == 1 && size == 12 &&
      sequence == this->native_snapshot_frame_.sequence &&
      this->native_snapshot_frame_.payload.size() == size &&
      std::equal(this->native_snapshot_frame_.payload.begin(), this->native_snapshot_frame_.payload.end(), payload);
  const bool configuration_read = this->configuration_read_active_ && this->configuration_read_sending_ &&
      operation == 1 && size == 12 && sequence == this->configuration_read_frame_.sequence &&
      this->configuration_read_frame_.payload.size() == size &&
      std::equal(this->configuration_read_frame_.payload.begin(), this->configuration_read_frame_.payload.end(), payload);
  if (!this->allow_tx_ || !(configuration_read || native_read || configuration || (operation == 1 && size == 2 && payload[0] == 1 && payload[1] == 4) ||
                           (operation == 3 && size == 4 && payload[2] == 0 && payload[3] == 0) ||
                           (this->enable_target_reports_ && operation == 2 && size == 4 &&
                            payload[0] == 1 && payload[1] == 0x12 && payload[2] == 4 && payload[3] == 1) ||
                           (this->enable_orientation_ && (operation == 4 || operation == 5) &&
                            ((size == 5 && payload[0] == 1 && payload[1] == 0x20 && payload[2] == 1) ||
                             (size == 4 && payload[0] == 1 && payload[1] == 0x43 && payload[2] == 0)))))
    return false;
  uint8_t bytes[56] = {0x55, 0, 1, sequence, operation, 0, static_cast<uint8_t>(size), 0};
  uint8_t sum = 0;
  for (size_t i = 0; i < 7; i++)
    sum += bytes[i];
  bytes[7] = static_cast<uint8_t>(0 - sum);
  for (size_t i = 0; i < size; i++)
    bytes[8 + i] = payload[i];
  uint16_t crc = 0xffff;
  for (size_t i = 0; i < 8 + size; i++) {
    crc ^= bytes[i];
    for (uint8_t bit = 0; bit < 8; bit++)
      crc = (crc & 1) ? (crc >> 1) ^ 0xa001 : crc >> 1;
  }
  bytes[8 + size] = static_cast<uint8_t>(crc);
  bytes[9 + size] = static_cast<uint8_t>(crc >> 8);
  this->write_array(bytes, size + 10);
  return true;
}

}  // namespace esphome::fp2
