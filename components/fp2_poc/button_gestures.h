#pragma once

#include <cstdint>
#include <vector>

namespace fp2_wire {

// Pure stock gesture vocabulary. Timer scheduling and application effects belong
// to adapters; timer inputs are delivered expiries, not elapsed-time guesses.
class ButtonGestures {
 public:
  enum class TimerCommand { START_PRESS, STOP_PRESS, START_RELEASE, STOP_RELEASE };
  struct Output {
    std::vector<uint8_t> events;
    std::vector<TimerCommand> timers;
  };
  explicit ButtonGestures(bool initial_high) : high_(initial_high), boot_low_(!initial_high) {}
  Output level(bool high);
  Output press_expired();
  Output release_expired(uint64_t uptime);

 private:
  bool high_;
  bool boot_low_;
  uint32_t clicks_{0};
  uint32_t held_{0};
};

}  // namespace fp2_wire
