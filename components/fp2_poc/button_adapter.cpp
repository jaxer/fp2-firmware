#include "button_adapter.h"

namespace fp2_wire {
void ButtonAdapter::initialize(bool pressed, uint32_t now) {
  gestures_.emplace(!pressed);
  press_timer_=release_timer_=false;
  previous_at_=now; uptime_=now;
}
void ButtonAdapter::advance_(uint32_t now) {
  uptime_+=uint32_t(now-previous_at_);
  previous_at_=now;
}
void ButtonAdapter::apply_(const ButtonGestures::Output &output, uint32_t now) {
  for (auto timer : output.timers) {
    switch (timer) {
      case ButtonGestures::TimerCommand::START_PRESS: press_timer_=true; press_at_=now; break;
      case ButtonGestures::TimerCommand::STOP_PRESS: press_timer_=false; break;
      case ButtonGestures::TimerCommand::START_RELEASE: release_timer_=true; release_at_=now; break;
      case ButtonGestures::TimerCommand::STOP_RELEASE: release_timer_=false; break;
    }
  }
}
std::vector<uint8_t> ButtonAdapter::level(bool pressed, uint32_t now) {
  if (!gestures_) return {};
  advance_(now);
  auto output=gestures_->level(!pressed);
  apply_(output,now);
  return output.events;
}
std::vector<uint8_t> ButtonAdapter::poll(uint32_t now) {
  if (!gestures_) return {};
  advance_(now);
  std::vector<uint8_t> events;
  // Catch up elapsed periodic deadlines; no synthetic edge is introduced.
  while (press_timer_ && uint32_t(now-press_at_)>=1000) {
    press_at_+=1000;
    auto output=gestures_->press_expired();
    events.insert(events.end(),output.events.begin(),output.events.end());
    apply_(output,now);
  }
  if (release_timer_ && uint32_t(now-release_at_)>=400) {
    release_timer_=false;
    auto output=gestures_->release_expired(uptime_);
    events.insert(events.end(),output.events.begin(),output.events.end());
    apply_(output,now);
  }
  return events;
}
}  // namespace fp2_wire
