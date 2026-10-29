#include "button_gestures.h"

namespace fp2_wire {

ButtonGestures::Output ButtonGestures::level(bool high) {
  if (high == high_) return {};
  high_ = high;
  if (!high) {
    ++clicks_;
    return {{0}, {TimerCommand::START_PRESS, TimerCommand::STOP_RELEASE}};
  }
  held_ = 0;
  return {{1}, {TimerCommand::STOP_PRESS, TimerCommand::START_RELEASE}};
}

ButtonGestures::Output ButtonGestures::press_expired() {
  // Accept queued expiries as stock does, including a timer/edge race. The
  // adapter must not turn this into a second independently clocked hold rule.
  if (++held_ != 10) return {};
  clicks_ = 0;
  return {{7}, {}};
}

ButtonGestures::Output ButtonGestures::release_expired(uint64_t uptime) {
  Output output;
  switch (clicks_) {
    case 1: output.events.push_back(2); break;
    case 2:
      output.events.push_back(3);
      if (boot_low_) {
        boot_low_ = false;  // Consumed even outside the boot gesture window.
        if (uptime <= 4000) output.events.push_back(8);
      }
      break;
    case 3: output.events.push_back(4); break;
    case 5: output.events.push_back(5); break;
    case 10: output.events.push_back(6); break;
    default: break;
  }
  clicks_ = 0;
  return output;
}

}  // namespace fp2_wire
