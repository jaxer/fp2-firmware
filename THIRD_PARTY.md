# Credits and third-party notices

- **[hansihe/esphome_fp2](https://github.com/hansihe/esphome_fp2)**: original FP2
  ESPHome/UART work and the [illustrated flashing guide](https://github.com/hansihe/esphome_fp2/blob/main/FLASHING.md).
  This repository links to that guide instead of copying its photographs or
  upstream implementation. It is an independent implementation informed by the
  published findings and further firmware/hardware investigation.
- **[ESPHome](https://github.com/esphome/esphome)**: MIT; compiled as a dependency.
  The build guard supplies a nonpersistent implementation of its preference
  interface and applies a narrowly pinned generated-source patch.
- **[ESP-IDF](https://github.com/espressif/esp-idf)**: Apache-2.0 and component-specific
  notices; supplied by the ESPHome toolchain.
- **[Lit](https://github.com/lit/lit)**: BSD-3-Clause; bundled into the cards.
  Preserve the generated bundle's license comments when distributing it.
- **[esbuild](https://github.com/evanw/esbuild)**: MIT; build dependency.
- **[esptool](https://github.com/espressif/esptool)**: GPL-2.0-or-later; separately
  installed research/flashing tool, not vendored here.

Aqara/Texas Instruments firmware remains proprietary. No vendor firmware image,
full dump or disassembly listing is distributed. Generated patched bundles include
vendor bytes and are not covered by this project's MIT license. Protocol findings,
small necessary instruction identities and project-authored patch source are
published for interoperability research. Aqara and ESPHome are their respective
owners' names; this is an independent project.
