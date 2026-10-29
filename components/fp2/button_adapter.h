#pragma once
#include "button_gestures.h"
#include <optional>

namespace fp2_wire {
// Local1000/400ms timing policy over explicit stock-domain timer inputs.
// No GPIO or effects. Initialize only from the first real published pin level.
class ButtonAdapter {
 public:
  void initialize(bool pressed, uint32_t now);
  bool initialized() const { return gestures_.has_value(); }
  std::vector<uint8_t> level(bool pressed, uint32_t now);
  std::vector<uint8_t> poll(uint32_t now);
 private:
  void advance_(uint32_t now);
  void apply_(const ButtonGestures::Output &output, uint32_t now);
  std::optional<ButtonGestures> gestures_;
  bool press_timer_{}, release_timer_{};
  uint32_t press_at_{}, release_at_{}, previous_at_{};
  uint64_t uptime_{};
};
}  // namespace fp2_wire
