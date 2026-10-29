#!/usr/bin/env python3
"""Local button timing policy against the actual pure gesture domain."""

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
#include "button_adapter.h"
#include <cassert>
#include <iostream>
using A=fp2_wire::ButtonAdapter;
void empty(const std::vector<uint8_t>&v){assert(v.empty());}
void click(A &a,uint32_t t){assert(a.level(true,t)==std::vector<uint8_t>{0});assert(a.level(false,t+20)==std::vector<uint8_t>{1});}
int main(){
 A uninitialized;empty(uninitialized.level(true,10));empty(uninitialized.poll(20000));assert(!uninitialized.initialized());
 A a;a.initialize(false,0);empty(a.level(false,0));empty(a.poll(1000));
 click(a,1100);empty(a.poll(1519));assert(a.poll(1520)==std::vector<uint8_t>{2});empty(a.poll(2000));
 click(a,2100);click(a,2200);empty(a.poll(2619));assert(a.poll(2620)==std::vector<uint8_t>{3});
 for(unsigned count : {3u,4u,5u,10u}){
  A b;b.initialize(false,0);for(unsigned i=0;i<count;++i)click(b,100+i*40);
  auto events=b.poll(100+(count-1)*40+20+400);
  auto expected=count==3?std::vector<uint8_t>{4}:count==5?std::vector<uint8_t>{5}:count==10?std::vector<uint8_t>{6}:std::vector<uint8_t>{};
  assert(events==expected);
 }
 A held;held.initialize(false,0);held.level(true,100);
 for(uint32_t t=1100;t<10100;t+=1000)empty(held.poll(t));
 assert(held.poll(10100)==std::vector<uint8_t>{7});empty(held.poll(20100));
 held.level(false,20200);empty(held.poll(20600)); // Held clicks were consumed.
 A catchup;catchup.initialize(false,0);catchup.level(true,100);
 assert(catchup.poll(10100)==std::vector<uint8_t>{7}); // Explicit elapsed tick catch-up.
 // First actual publication low must not synthesize a press or start hold timer.
 A boot;boot.initialize(true,100);empty(boot.level(true,100));empty(boot.poll(200));
 boot.level(false,300);empty(boot.poll(700));
 click(boot,1000);click(boot,1100);assert(boot.poll(1520)==std::vector<uint8_t>({3,8}));
 click(boot,1600);click(boot,1700);assert(boot.poll(2120)==std::vector<uint8_t>{3});
 // Poll/edge timestamps cross32-bit wrap; uptime extends rather than replaying boot gesture.
 A wrap;wrap.initialize(true,UINT32_MAX-200);wrap.level(false,UINT32_MAX-100);
 click(wrap,UINT32_MAX-50);click(wrap,50);
 assert(wrap.poll(470)==std::vector<uint8_t>{3}); // No event8 after uptime wrapped.
 A hold_wrap;hold_wrap.initialize(false,UINT32_MAX-200);hold_wrap.level(true,UINT32_MAX-100);
 assert(hold_wrap.poll(uint32_t(UINT32_MAX-100+10000u))==std::vector<uint8_t>{7});
 // Duplicate levels do not reset deadlines; exact400ms remains inclusive.
 A duplicate;duplicate.initialize(false,0);duplicate.level(true,100);duplicate.level(true,1100);
 assert(duplicate.poll(10100)==std::vector<uint8_t>{7});
 std::cout<<"button adapter checks passed\n";
}
"""


def run_tests():
    with tempfile.TemporaryDirectory(prefix="fp2-button-adapter-") as temporary:
        target = Path(temporary)
        (target / "test.cpp").write_text(HARNESS)
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
                str(component / "button_adapter.cpp"),
                str(component / "button_gestures.cpp"),
                "-o",
                str(target / "test"),
            ],
            check=True,
        )
        result = subprocess.run([str(target / "test")], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "button adapter checks passed"
    return {
        "local_timer_periods_ms": [1000, 400],
        "sanitizers": ["address", "undefined"],
        "hardware_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(run_tests(), indent=2))
