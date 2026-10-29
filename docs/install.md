# Install on an Aqara FP2

Open the FP2, back up its firmware, and install the replacement. Future updates
can go over Wi-Fi.

You need a **3.3 V FTDI/USB-to-serial adapter**, five wires, soldering tools and
USB power for the FP2. On your computer, install Python 3.13,
[uv](https://docs.astral.sh/uv/), `make` and a C++ compiler.

Run all commands from this repository’s folder.

## 1. Open the case

Unplug the FP2. Remove the four rubber plugs on the back, then the four screws.
Carefully separate the halves; the small USB board will unplug from the main board.

Use [hansihe’s annotated board picture](https://github.com/hansihe/esphome_fp2/blob/main/FLASHING.md#connecting-wires)
to find the solder points. Follow the **annotated diagram**, not the photograph
of attached wires—the author notes that one wire in that photograph is wrong.

## 2. Connect the adapter

Set the adapter to **3.3 V logic**, then connect:

| Adapter | FP2 |
| --- | --- |
| GND | GND |
| RX | TX |
| TX | RX |
| DTR | GPIO0 |
| RTS | RST / EN |

Leave the adapter’s power pin disconnected. Reconnect the FP2’s USB board and
power the FP2 through its own USB connector. Plug the adapter into your computer.

Replace `/dev/ttyUSB0` with your adapter’s serial port. On macOS, it usually
starts with `/dev/cu.usbserial`. Set it once for the commands that follow:

```sh
FP2_PORT=/dev/ttyUSB0
```

## 3. Save the original firmware

First check that the device allows flashing:

```sh
uv run --with esptool==5.6.0 esptool --chip esp32 --port "$FP2_PORT" get-security-info
```

Continue only if **secure boot and flash encryption are disabled**. If either is
enabled, stop: this guide does not cover that device.

Now make the backup:

```sh
mkdir -p .tools
uv run --with esptool==5.6.0 esptool --chip esp32 --port "$FP2_PORT" --baud 115200 read-flash 0 0x1000000 .tools/stock.bin
```

Wait for it to finish. `stock.bin` should be **16 MiB**. Keep a second, private
copy labelled for this FP2—it may contain passwords and calibration data.

## 4. Build the new firmware

```sh
python3 tools/configure.py
```

Enter your Wi-Fi name and password. Keep the resulting `firmware/secrets.yaml`;
you’ll need it for Home Assistant and future updates.

Then build:

```sh
make firmware
```

The first build downloads the compiler, so give it time. Use this build, not
the GitHub Actions image, which has test-only credentials.

## 5. Install the radar helper

The FP2 has a separate radar processor. It needs a small helper so our firmware
can read its settings.

**Keep power connected throughout this update. An interruption may leave the
radar unusable; recovery is not yet proven.**

Follow [the radar installation steps](radar.md#inputs-and-tools) using
`.tools/stock.bin` and the same serial port. Finish installation and inspection,
then return here. If the tool rejects your firmware version, stop.

## 6. Write the ESP32 firmware

Prepare the file to flash:

```sh
python3 tools/install_plan.py .tools/stock.bin
```

Find the `offset` value in the output. Replace `OFFSET` below with that value.
This is where the app will be written. **Never use zero or run an erase command.**

```sh
uv run --with esptool==5.6.0 esptool --chip esp32 --port "$FP2_PORT" --baud 115200 write-flash OFFSET .tools/install/app.bin
```

Check the write, using the same offset:

```sh
uv run --with esptool==5.6.0 esptool --chip esp32 --port "$FP2_PORT" --baud 115200 verify-flash OFFSET .tools/install/app.bin
```

Both commands must finish successfully before you continue.

## 7. Add it to Home Assistant

Home Assistant should discover an ESPHome device named **FP2**. If it doesn’t,
add an ESPHome integration manually with the address `fp2.local`.

When asked for the encryption key, use `api_encryption_key` from
`firmware/secrets.yaml`. Allow the device to perform Home Assistant actions in the integration’s options;
the live target map needs this.

Follow [the card setup guide](home-assistant.md) to add the map and zone editor.
Check that presence changes when you move in front of the sensor.

## 8. Close the case

Unplug both USB cables and disconnect all adapter wires. Reconnect **only the
FP2’s USB power** and check that it comes back online in Home Assistant.

Once it comes back online, close the case and mount it. Check detection again
in its final position.

## Later: update over Wi-Fi

Keep the same `secrets.yaml`. From this repository’s folder, run:

```sh
make firmware
uv run --python 3.13 --with esphome==2026.8.2 esphome upload firmware/fp2-normal.yaml --device fp2.local
```

This updates the ESP32. You don’t need to repeat the radar installation.
