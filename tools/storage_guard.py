"""PlatformIO pre-build guard: replace only generated, pinned preferences with nonpersistent stubs."""

from pathlib import Path
import hashlib

ORIGINAL_SHA256 = "c9e26028ac205ad0ea9fe62fa3d89789b6ccfc01ac098d2270fa1032c544f9b3"
STUB = """// FP2 firmware: preferences intentionally nonpersistent.
#include "esphome/core/preferences.h"
#ifdef USE_ESP32
namespace esphome::esp32 {
bool ESP32PreferenceBackend::save(const uint8_t *, size_t) { return false; }
bool ESP32PreferenceBackend::load(uint8_t *, size_t) { return false; }
void ESP32Preferences::open() { this->nvs_handle = 0; }
ESPPreferenceObject ESP32Preferences::make_preference(size_t, uint32_t, bool) { return {}; }
ESPPreferenceObject ESP32Preferences::make_preference(size_t, uint32_t) { return {}; }
bool ESP32Preferences::load_from_key(uint32_t, uint8_t *, size_t) { return false; }
bool ESP32Preferences::sync() { return true; }
bool ESP32Preferences::reset() { return false; }
static ESP32Preferences s_preferences;
ESP32Preferences *get_preferences() { return &s_preferences; }
void setup_preferences() { s_preferences.open(); global_preferences = &s_preferences; }
}
namespace esphome { ESPPreferences *global_preferences; }
#endif
"""


def patch(project):
    path = Path(project) / "src/esphome/components/esp32/preferences.cpp"
    original = path.read_bytes()
    if original == STUB.encode():
        patch_hal(project)
        return
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise RuntimeError(
            "FP2 storage guard: unexpected ESPHome preferences source; refuse build"
        )
    path.write_text(STUB)
    print("FP2: nonpersistent preferences guard applied to generated source")
    patch_hal(project)


HAL_SHA256 = "8c466270d6a8b89cc47c671cd168e472551b48b7997440d7f41b9a7e7610fd1a"
HAL_CALL = "  esp_ota_mark_app_valid_cancel_rollback();"
HAL_REPLACEMENT = (
    "  // FP2 firmware: preserve existing stock OTA metadata; no mark-valid write."
)


def patch_hal(project):
    path = Path(project) / "src/esphome/components/esp32/hal.cpp"
    source = path.read_text()
    if HAL_REPLACEMENT in source and HAL_CALL not in source:
        return
    if (
        hashlib.sha256(path.read_bytes()).hexdigest() != HAL_SHA256
        or source.count(HAL_CALL) != 1
    ):
        raise RuntimeError(
            "FP2 boot metadata guard: unexpected HAL source; refuse build"
        )
    path.write_text(source.replace(HAL_CALL, HAL_REPLACEMENT))
    print("FP2: stock OTA metadata preservation guard applied")
