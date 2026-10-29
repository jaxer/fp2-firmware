#!/usr/bin/env python3
"""Compile the pure stock button machine; no GPIO, timers or device effects."""

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
#include "button_gestures.h"
#include <cassert>
#include <iostream>
using B = fp2_wire::ButtonGestures;
void empty(const B::Output &o) { assert(o.events.empty() && o.timers.empty()); }
void click(B &b) {
 auto down=b.level(false);
 assert(down.events==std::vector<uint8_t>{0});
 assert(down.timers==std::vector<B::TimerCommand>({B::TimerCommand::START_PRESS,B::TimerCommand::STOP_RELEASE}));
 empty(b.level(false));
 auto up=b.level(true);
 assert(up.events==std::vector<uint8_t>{1});
 assert(up.timers==std::vector<B::TimerCommand>({B::TimerCommand::STOP_PRESS,B::TimerCommand::START_RELEASE}));
 empty(b.level(true));
}
int main() {
 B initial(true); empty(initial.level(true)); empty(initial.release_expired(0));
 for(unsigned count=1;count<=12;++count) {
  B b(true); for(unsigned i=0;i<count;++i) click(b);
  std::vector<uint8_t> expected;
  switch(count) { case 1:expected={2};break;case 2:expected={3};break;
   case 3:expected={4};break;case 5:expected={5};break;case 10:expected={6};break; }
  auto out=b.release_expired(9000);assert(out.events==expected && out.timers.empty());
  empty(b.release_expired(9001)); // Counts clear, including unmatched4/6/7/8/9.
  click(b);assert(b.release_expired(9002).events==std::vector<uint8_t>{2});
 }
 B held(true);held.level(false);
 for(unsigned i=1;i<10;++i) empty(held.press_expired());
 assert(held.press_expired().events==std::vector<uint8_t>{7});
 for(unsigned i=0;i<20;++i) empty(held.press_expired()); // Threshold, not periodic7.
 held.level(true);empty(held.release_expired(20000)); // No click after hold.
 held.level(false);
 for(unsigned i=1;i<10;++i) empty(held.press_expired());
 assert(held.press_expired().events==std::vector<uint8_t>{7}); // Release reset held.
 // Boot-low initializes cached level only: no press/click/hold is synthesized.
 for(uint64_t uptime : {uint64_t(3999),uint64_t(4000),uint64_t(4001),uint64_t(0x100000000ULL)}) {
  B boot(false);empty(boot.level(false));empty(boot.release_expired(0));
  assert(boot.level(true).events==std::vector<uint8_t>{1});
  click(boot);click(boot);
  auto expected=uptime<=4000?std::vector<uint8_t>{3,8}:std::vector<uint8_t>{3};
  assert(boot.release_expired(uptime).events==expected);
  click(boot);click(boot);
  assert(boot.release_expired(1).events==std::vector<uint8_t>{3}); // Flag consumed even when late.
 }
 B retained(false);retained.level(true);click(retained);
 assert(retained.release_expired(100).events==std::vector<uint8_t>{2});
 click(retained);click(retained);
 assert(retained.release_expired(4000).events==std::vector<uint8_t>({3,8})); // Single did not consume flag.
 // Queued timer expiries remain explicit inputs even after an edge; no hidden
 // clock or level-based suppression is introduced by the domain.
 B queued(true);for(unsigned i=1;i<10;++i)empty(queued.press_expired());
 assert(queued.press_expired().events==std::vector<uint8_t>{7});
 std::cout << "button gesture checks passed\n";
}
"""


def run_tests():
    with tempfile.TemporaryDirectory(prefix="fp2-button-gestures-") as temporary:
        target = Path(temporary)
        (target / "test.cpp").write_text(HARNESS)
        binary = target / "test"
        component = ROOT / "components/fp2_poc"
        subprocess.run(
            [
                "c++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer",
                "-I",
                str(component),
                str(target / "test.cpp"),
                str(component / "button_gestures.cpp"),
                "-o",
                str(binary),
            ],
            check=True,
        )
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "button gesture checks passed"
    return {
        "click_counts_checked": 12,
        "hold_threshold": 10,
        "boot_window_boundary": [3999, 4000, 4001, 4294967296],
        "sanitizers": ["address", "undefined"],
        "hardware_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(run_tests(), indent=2))
