#pragma once
#include "protocol.h"
#include <array>

namespace fp2_wire {
class ConfigurationReader {
 public:
  enum class Kind { ZONE, SCALAR, SPECIAL_MAP };
  struct Result {
    Kind kind{Kind::ZONE};
    uint16_t attribute{};
    uint8_t zone_id{},active_byte{},sensitivity{},type{},close_away{};
    uint32_t instance{},map_pointer{},raw_value{},started_at{},completed_at{},requests{};
    int64_t wire_value{}; //0106 inversion is exactly3-stored; preserve unsupported values.
    std::array<uint8_t,40> mask{};
  };
  bool start_zone(uint32_t zone_id,uint32_t now);
  bool start_scalar(uint32_t attribute,uint32_t now);
  bool start_special_map(uint32_t attribute,uint32_t now);
  bool next_request(uint32_t now,uint8_t sequence,Frame &out);
  bool ingest(const Frame &frame,uint32_t now);
  bool complete() const { return phase_==Phase::DONE; }
  bool failed() const { return phase_==Phase::ERROR; }
  const Result &result() const { return result_; }
 private:
  enum class Phase { PREFIX, INSTANCE, FIRST, MIDDLE_INSTANCE, SECOND, FINAL_INSTANCE, DONE, ERROR };
  bool begin_(Kind kind,uint16_t attribute,uint8_t zone_id,uint32_t now);
  bool expired_(uint32_t now);
  void fail_();
  void finish_(uint32_t now);
  uint8_t fields_() const;
  Phase phase_{Phase::ERROR};
  Result result_{};
  std::array<std::vector<uint8_t>,6> first_{};
  uint8_t field_{},pending_count_{};
  uint32_t pending_address_{},pending_at_{};
  bool pending_{};
};
// Pure research readback: complete() proves sequential repeated RAM agreement,
// not persistence, atomicity, semantic enum validity or a successful setter.
}  // namespace fp2_wire
