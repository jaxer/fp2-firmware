#!/usr/bin/env python3
"""Isolated native tests of source-derived stock light arithmetic, no device I/O."""

import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HARNESS = r"""
#include "light_filter.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
using namespace fp2_wire;
uint16_t word(uint32_t reading) {
  for (unsigned w=0;w<65536;++w) if (LightFilter::decode(w)==reading) return w;
  assert(false);return 0;
}
uint32_t uniform(uint32_t reading, const LightCalibration &c={}) {
  LightFilter f(c); const auto w=word(reading);
  for (int i=1;i<=20;++i) assert(f.update(w)==(i==20));
  return f.lux();
}
int main() {
  for (uint32_t w=0;w<65536;++w) {
    const uint32_t expected=((uint32_t{1}<<(w>>12))*(w&4095))/100;
    assert(LightFilter::decode(w)==expected);
    assert(LightFilter::decode(w)<=1341849);
  }
  LightCalibration identity; identity.low_k=identity.high_k=1;
  identity.low_max=identity.high_max=2000000;
  LightFilter startup(identity);
  assert(startup.lux()==0);
  for(int i=1;i<=19;++i) assert(!startup.update(word(10)));
  assert(startup.update(word(10)) && startup.lux()==10);
  assert(startup.update(word(20)) && startup.lux()==10); // Trim the single maximum.
  for(int i=0;i<1000;++i) assert(startup.update(word(10)));
  // Preserve slot0-zero minimum quirk, then replace slot0 on safe call21.
  LightFilter zero_first(identity);
  for(int i=0;i<11;++i) assert(!zero_first.update(0));
  for(int i=0;i<8;++i) assert(!zero_first.update(word(10)));
  assert(zero_first.update(word(10)) && zero_first.lux()==11);
  assert(zero_first.update(word(10)) && zero_first.lux()==10);
  for(int i=0;i<10;++i) assert(zero_first.update(0));
  assert(zero_first.lux()==0);
  // Count1/count2 averages and zero bypass rather than intercept correction.
  LightFilter sparse(identity);
  for(int i=0;i<19;++i) assert(!sparse.update(0));
  assert(sparse.update(word(20)) && sparse.lux()==20);
  assert(sparse.update(word(10)) && sparse.lux()==15);
  LightCalibration c;
  c.low_k=2;c.low_max=50;
  assert(uniform(20,c)==40); // Raw below cutoff; calibrated below too.
  assert(uniform(30,c)==119); // Raw30<50 but calibrated60>50 selects FH.
  c.low_max=40; assert(uniform(20,c)==40); // Equality retains low calibration.
  c.low_b=-50; assert(uniform(20,c)==80); // Negative -> unsigned cutoff -> FH.
  c={};c.high_k=2;c.high_min=50;c.high_max=100;
  assert(uniform(20,c)==78); // Calibrated40<50 selects FL.
  c.high_min=40;assert(uniform(20,c)==40);
  c.high_b=-50;assert(uniform(20,c)==0); // Negative unsigned value bypasses FL.
  c={};c.low_k=2;c.high_k=3;c.low_max=20;c.high_max=100;
  assert(uniform(20,c)==40 && uniform(21,c)==63);
  // Partial-key paths preserve source flow rather than idealized usable ranges.
  c.low_k=-1;assert(uniform(20,c)==0);
  c={};c.low_k=-1;c.high_k=2;c.high_min=50;c.high_max=100;
  assert(uniform(20,c)==78); // Negative other slope passes '<epsilon'.
  c.low_k=0.001f;assert(uniform(20,c)==40); // Fails '<epsilon': ordinary split.
  assert(uniform(40)==155 && uniform(42)==165); // FL155/FL163 -> FH165.
  c={};c.low_k=c.high_k=1;c.low_b=c.high_b=100;
  c.low_max=c.high_max=2000000;
  assert(uniform(0,c)==0); // Dark readings never receive an intercept.
  assert(uniform(1341849,c)==83000);
  c.low_b=-3276.8f;assert(uniform(10,c)==0);
  // Real representable factory coefficient144/1000: FMA would truncate43.
  c={};c.low_k=144.0f/1000.0f;c.low_b=-100.0f;
  c.low_max=c.high_max=2000000;c.high_k=1;
  assert(std::trunc(std::fma(1000.0f,c.low_k,c.low_b))==43);
  assert(uniform(1000,c)==44);
  // Invalid API inputs remain defined; these are not valid factory values.
  c.low_k=std::numeric_limits<float>::infinity();assert(uniform(20,c)==83000);
  c.low_k=1;c.low_b=std::numeric_limits<float>::quiet_NaN();assert(uniform(20,c)==0);
  std::cout << "65536 raw words, startup20/21, ring and calibration boundaries passed\n";
}
"""


def run_tests():
    with tempfile.TemporaryDirectory(prefix="fp2-light-filter-") as directory:
        temp = pathlib.Path(directory)
        source, binary = temp / "light_test.cpp", temp / "light_test"
        source.write_text(HARNESS)
        command = [
            "clang++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffp-contract=fast",
            "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
            "-I",
            str(ROOT / "components/fp2_poc"),
            str(source),
            str(ROOT / "components/fp2_poc/light_filter.cpp"),
            "-o",
            str(binary),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        result = subprocess.run(
            [str(binary)], check=True, capture_output=True, text=True
        )
        return {
            "raw_words": 65536,
            "sanitizers": ["address", "undefined"],
            "result": result.stdout.strip(),
        }


if __name__ == "__main__":
    print(json.dumps(run_tests(), indent=2))
