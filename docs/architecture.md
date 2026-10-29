# Architecture

Rules are pure C++ or TypeScript. Adapters own hardware, Home Assistant and
storage. Configuration files and views connect them. The ESPHome component is named
`fp2`; its adapter class is `FP2Component`.

```text
ESP32
  ESPHome YAML                         configuration / wiring
       │
  fp2.cpp                              scheduler / API / UART adapter
       ├── protocol                     framing and scalar validation
       ├── occupancy, targets           authoritative report state
       ├── normal_commands              bounded command builders
       ├── configuration_reader         monitor read transaction
       ├── native_snapshot              atomic configuration observation
       ├── learning                     explicit learning lifecycle
       └── orientation, light_filter    sensor rules
            ↑ sensor adapters supply measurements and caller-supplied time

Home Assistant cards
  card / glance / editor               views and user actions
       │
  client                               authenticated HA connection / lifecycle
       ├── protocol                     geometry and payload rules
       ├── cache                        validated configuration snapshots
       └── localization                 English / Russian labels

Research tools
  research.py                          explicit hardware workflow
       ├── ram_bridge / rom_transport   bounded ESP32 ROM upload and UART transport
       ├── radar_update / radar_xmodem   updater transaction
       └── radar_memory_monitor         validated reads and aligned RAM writes
```

## Boundaries

- Domain modules have no ESPHome dependency; time is supplied as an argument.
  They reject malformed input before changing state.
- The ESPHome adapter serializes radar requests. Configuration mutations are sent
  once; acknowledgement is not proof of application or persistence. The card
  requests fresh readback before declaring success.
- Native zone occupancy is distinct from coordinate-derived host regions. Unknown
  data stays unknown. A radar track is not a guaranteed person.
- Configuration snapshots live in a hidden HA dashboard. Live occupancy and
  target freshness never come from this cache. Transport uses the authenticated
  HA frontend connection; the bundle contains no token.
- The normal ESP32 app never erases shared factory storage. Pinned build guards
  disable persistent ESPHome preferences and automatic boot-valid writes while
  retaining authenticated app-only OTA.
- Radar monitor code is a small Cortex-R4 extension; vendor MSS/DSS/BSS images
  remain inputs, not repository contents. The RAM bridge runs on the ESP32
  temporarily and restores normal boot after successful operations.

## Tests

`make fast` runs isolated C++ domain harnesses with ASan/UBSan, Python transport
contracts and card tests. Fixtures are synthetic isolated contract inputs,
clearly labelled; they establish software behavior, not hardware acceptance.
`make area` adds the bundle and public-tree audit. `make gate` also builds the
pinned ESP32 image. No test opens a serial port or changes Home Assistant.

Each run owns temporary compilation directories. Firmware build output is local
to the checkout; use separate checkouts for concurrent firmware builds. Hardware
work requires exclusive access to the serial adapter.

## Hardware interfaces

| Interface | ESP32 connection | Implementation |
| --- | --- | --- |
| Programming UART0 | Board TX/RX, EN, GPIO0 | FTDI connection in the installation guide |
| Radar UART2 | RX18, TX19; nominal 921600 8N1 | Framing adapter and monitor bridge |
| Radar reset | GPIO13 | Explicit research bridge only; normal app does not drive it |
| Sensor I²C | SDA33, SCL32, 400 kHz | Orientation and illuminance adapters |
| Board button | GPIO36 input | Debounced gesture events; no erase/pairing side effects |
| RGB LED | GPIO14/26/27, inverted PWM | Internal board-control package |

The observed accelerometer responds at I²C address `27` hex with chip ID `13`
hex; that ID alone is not a unique model identification. Failed/partial readings
do not refresh orientation. Button polarity, visible RGB assignment and optical
accuracy remain separate from successful registration or compilation.
