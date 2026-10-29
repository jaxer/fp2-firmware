# Installation

Start with your own unit and preserve its backup. The FP2's USB connector powers
it; it does not provide an ESP32 programming interface. First installation uses
3.3 V UART. Later ESP32 updates use authenticated Wi-Fi OTA.

## 1. Open and connect

Remove the four rubber plugs and screws on the back. Separate the housing
carefully: the USB daughterboard disconnects from its header. Protect the antenna
cable if lifting the main PCB. See the original author's
[illustrated disassembly and test-point guide](https://github.com/hansihe/esphome_fp2/blob/main/FLASHING.md).
Its annotated connection diagram is the reference; a photograph of soldered
wires is explicitly noted upstream to contain one wrong connection.

| FP2 point | FTDI / USB UART | Purpose |
| --- | --- | --- |
| GND | GND | Common reference |
| TX (ESP32 transmit) | RX | Read ESP32 UART0 |
| RX (ESP32 receive) | TX | Write ESP32 UART0 |
| GPIO0 | DTR, or temporarily GND | ROM download selection |
| RST / EN | RTS, or manual reset | Reset / boot control |
| USB daughterboard | Separate USB power | Power the FP2 |

```text
USB UART (3.3 V logic)        FP2 / ESP32
TX ────────────────────────► RX
RX ◄──────────────────────── TX
GND ──────────────────────── GND
DTR ──────────────────────── GPIO0
RTS ──────────────────────── EN / RST

Separate USB supply ────────► FP2 USB daughterboard
```

Do not connect 5 V UART logic or power the device from the adapter's 3.3 V pin.
EN is the ESP32 module reset/enable pad, not a nearby arbitrary test point. Match
pad locations to the linked annotated board diagram. No radar wiring is needed.

With manual control: hold GPIO0 low, pulse EN low then release EN, and release
GPIO0 after download mode is entered. Automatic DTR/RTS was tested with an FT232RL;
adapter polarity/reset circuits can differ. Disconnect an unpowered adapter's
signal wires before normal use: it can hold the ESP32 in reset/download mode.

## 2. Back up before writing

Use a fresh directory outside the repository. Replace `PORT` with your adapter
(e.g. `/dev/ttyUSB0`, `/dev/ttyACM0`, or `/dev/cu.usbserial-…`).

```sh
uv run --with esptool==5.6.0 esptool --chip esp32 --port PORT get-security-info
uv run --with esptool==5.6.0 esptool --chip esp32 --port PORT --baud 115200 read-flash 0 0x1000000 stock.bin
shasum -a 256 stock.bin
```

Keep the 16 MiB backup private and associated with that physical unit. It can
contain credentials and unit-specific calibration. Continue only if flash
encryption and secure boot are disabled and normal ROM download is available.
A valid backup does not prove interrupted radar-update recovery.

## 3. Build your ESP32 image

```sh
python3 tools/configure.py
make firmware
```

`configure.py` prompts for Wi-Fi credentials and creates a private API key and OTA
password. Keep `firmware/secrets.yaml`; losing the OTA password can require serial
access. Build output is app-only. Do not use the disposable-credential CI image.
This build also installs the toolchain needed for the temporary RAM bridge.

## 4. Install the monitor and ESP32 app

The normal profile currently reads saved configuration/calibration through the
monitor extension. A stock radar without it is not a complete installation of
this profile. Follow [Radar tools](radar.md) using `stock.bin`, including the
explicit recovery-risk decision, install and monitor inspection. The extension
changes radar code, not signal-processing algorithms. Unsupported vendor bundles
are rejected; do not replace the expected hash to force installation.

This stage runs a temporary ESP32 RAM bridge; it does not replace the ESP32 app.
Then prepare the app-only plan:

```sh
python3 tools/install_plan.py /path/to/stock.bin
```

The plan validates the supported stock bootloader, partition layout, OTA selector
and app integrity. It writes `.tools/install/plan.json`, a sector-padded app and a
selected-slot restoration image. Read its `offset` and `payload` fields. The
backup's boot metadata must still match the device; re-read it if in doubt.

```sh
# Replace OFFSET with the plan's offset, not zero.
uv run --with esptool==5.6.0 esptool --chip esp32 --port PORT --baud 115200 write-flash OFFSET .tools/install/app.bin
uv run --with esptool==5.6.0 esptool --chip esp32 --port PORT --baud 115200 verify-flash OFFSET .tools/install/app.bin
```

Never erase the whole flash or flash a merged factory image. The stock bootloader,
partition table, OTA records and factory/calibration partitions must be retained.
If restoring the app, use the same plan's offset and `restore-app.bin`; this does
not undo radar changes or restore altered radar settings.

## 5. Connect and reassemble

Discover `fp2.local` in Home Assistant's ESPHome integration. Supply the API
key from `firmware/secrets.yaml` when prompted. Confirm live presence/native zones
and install the [cards](home-assistant.md). Enable the ESPHome integration's
permission for the device to perform HA actions so target events can be emitted.

Disconnect the FTDI wires, insulate/remove loose leads, and test a USB-only cold
boot before reassembling. Initial radar configuration reads take about a minute;
opening a cached card does not repeat them. Validate detection and zone boundaries
in the actual mounting position.

For later updates, compile with the same private credentials and run the pinned
ESPHome uploader against `firmware/fp2-normal.yaml` / `fp2.local`. These are ESP32
app updates; radar updates remain an explicit research procedure.

```sh
uv run --python 3.13 --with esphome==2026.8.2 esphome upload firmware/fp2-normal.yaml --device fp2.local
```
