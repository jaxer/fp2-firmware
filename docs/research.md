# Protocol research and evidence boundaries

The implementation is informed by static analysis of stock ESP32/radar firmware, independently checked wire captures, and isolated replay tests. These sources answer different questions: decoded instructions establish a particular image's behavior; captures establish observed exchanges; neither alone certifies every installed version or physical measurement.

See the [protocol reference](protocol.md) for the usable contract, [architecture](architecture.md) for implementation boundaries, [radar integration](radar.md) for operational policy, [installation](install.md) for recovery requirements, and [Home Assistant](home-assistant.md) for exposed state.

## Version and address conventions

The host analysis covers the ESP32 app build `bf42e5a3` dated 2026-04-15. Historical captures include radar version bytes 86, 98 and 99; these bytes do not uniquely identify all MSS/DSP/bootloader members. Mode-specific main, fall and sleep packages have distinct code mappings. Semantic findings must not be transferred solely because their attribute dispatch IDs match.

Addresses below identify the analyzed stock builds, not stable APIs. Main-MSS addresses are low runtime addresses. Installed first-stage bootloader addresses use its independently reconstructed relocated runtime mapping; staged bootloader mappings differ. No firmware images, household configurations or acquisition receipts are distributed here.

## Selected findings

| Finding | Source locations and strength |
| --- | --- |
| Frame construction, CRC and scalar/container encoding | Host 0x400e7878–0x400e7f24; framing independently corroborated by valid captured packets |
| Status ACK grammar | Host 0x400de7f4 builds op3/tag 0/status; 0x400e1390 checks tag 0/status 0; sequence matching is not universal |
| Typed-parser bounds | Main MSS 0x1b844 accepts tags 0/1/2/4/5/6, with an insufficient generic minimum-length guard; strict decoding is required |
| Zone shape and mutation | Main 0xc944 and 0xf9ec establish 40-byte masks, 20 × 16-bit layout, zone-ID limits and geometry changes |
| Geometry/property reset distinction | Creation/deletion branches 0xca4c/0xcb84 reset properties; changed nonempty maps preserve them |
| Overlap property priority | Helpers 0x249f0/0x24a48 return the first matching zone's sensitivity/type; native occupancy separately evaluates every zone |
| Independent map persistence |0x20300 writes 1280 raw-mask bytes; 0x7f00 dispatches deferred writes; boot reconstruction begins around 0x191a |
| Learning lifecycle |0x166ac resets tracker state; 0x26414 arms accumulation; 0x24c58 stores learned data and emits completion; 0x13734 constructs automatic-edge results |
| Target format |0x12ae4 emits 14-byte records from 33-byte internal records; 0xbb24 constructs those internal records |
| Model speed meaning | Prediction 0x158c4 uses the matrix constructed around 0xc178: x′=x+h·u, y′=y+h·v; physical units remain open |
| SNR field meaning | Producer 0xbdb6 supplies the same internal value to a compiled SNR-labelled formatter and 0xbdee copies it into the packed record; dB interpretation is unproved |
| Processing cadence | Internal mailbox→tracker→report tasks, including 0x18750/0x19c5c/0x27250, establish event-driven passes; 0117 is a throttled view |
| Installed update receiver | Installed SBL0 receiver 0x08002f20, erase/download caller 0x080086cc and page writer 0x0800977c establish erase-before-readiness and ACK-before-tail-flush |

A string, enum, dispatch case or successful ACK is not sufficient by itself to establish a feature. Negative searches are bounded: an undiscovered getter or producer is not proof that every firmware version lacks it.

## Important unresolved facts

- Physical coordinate scale, mounting axes and speed time units; calibrated meanings for SNR/status/pose.
- Complete supported mode/property enums and safe transitions across installed versions. In the analyzed main image, 0116 readback can itself change runtime mode.
- A standard vendor-UART current-zone export/readback contract without the monitor, durable multi-record save acceptance and interrupted-save behavior.
- The full association cause of split/retained tracks, live private tracker predicates and synchronized physical motion-to-actuation latency.
- Cross-version updater compatibility, authenticity policy, controlled interruption acceptance and independent recovery. Discovering the receiver does not establish safe upgrades.

Raw protocol values are retained where meaning is incomplete. Target count means reported tracks, not certified people. Native occupancy remains separate from target visualization and host-defined regions.

## Related public material

The independent [Aqara FP2 reverse-engineering project](https://github.com/hansihe/AqaraPresenceSensorFP2ReverseEngineering) provides hardware observations and historical protocol/capture material. Its names and earlier operation descriptions are research leads; the contract here follows checked producer/parser behavior where they differ. Texas Instruments' [SWRU520E technical reference manual](https://www.ti.com/lit/ug/swru520e/swru520e.pdf) supplies 68xx register context, with part and silicon applicability checked separately.

Public documentation describes methods and necessary protocol constants rather than redistributing proprietary firmware or installation-specific data.

## Reconstruct analysis views

The exporters reconstruct initialized runtime views for the supported bundled
MSS applications and staged bootloaders. They verify instruction context,
initializer tables, decompression bounds and source hashes. Output ELFs are
analysis containers, not executable replacement images or observations of live RAM.

```sh
python3 tools/inspect_flash.py /path/to/stock.bin > .tools/esp32.json
python3 tools/inspect_radar_package.py /path/to/stock.bin \
  --export-arm-dir .tools/radar > .tools/radar-package.json
python3 tools/export_runtime_elf.py /path/to/stock.bin --output .tools/sbl0-runtime.elf
python3 tools/export_second_sbl_elf.py /path/to/stock.bin --output .tools/sbl1-runtime.elf
python3 tools/export_app_runtime_elf.py /path/to/stock.bin --output .tools/main-runtime.elf
python3 tools/export_fall_runtime_elf.py /path/to/stock.bin --output .tools/fall-runtime.elf
python3 tools/export_sleep_runtime_elf.py /path/to/stock.bin --output .tools/sleep-runtime.elf
```

Use GNU `arm-none-eabi-objdump` for ARM/Thumb; select Thumb explicitly for known
Thumb functions if mapping symbols are absent. `tools/build_tic6x_objdump.py`
builds a hash-pinned GNU binutils disassembler for DSP analysis under `.tools/`;
it does not install system software. Proprietary bytes in exported ELFs and
resulting disassemblies stay private.
