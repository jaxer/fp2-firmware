import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from ota_policy import audit_ota_main, audit_ota_defines

MAIN = """new(normal_ota) esphome::ESPHomeOTAComponent();
normal_ota->set_port(3232);
normal_ota->set_auth_password("isolated-test-password");"""
DEFINES = "#define USE_OTA\n#define USE_OTA_PASSWORD\n#define USE_OTA_VERSION 2\n"


class NativeOTAPolicy(unittest.TestCase):
    def test_normal_app_only_native_ota(self):
        audit_ota_main("normal", MAIN)
        audit_ota_defines("normal", DEFINES)

    def test_other_profiles_cannot_enable_ota(self):
        for profile in ["passive", "mvp", "i2c-diagnostic"]:
            audit_ota_main(profile, "")
            audit_ota_defines(profile, "")
            with self.assertRaises(ValueError):
                audit_ota_main(profile, MAIN)
            with self.assertRaises(ValueError):
                audit_ota_defines(profile, DEFINES)

    def test_password_port_and_component_required(self):
        for main in [
            "",
            MAIN.replace("3232", "80"),
            MAIN.replace("isolated-test-password", ""),
            MAIN + MAIN,
        ]:
            with self.assertRaises(ValueError):
                audit_ota_main("normal", main)

    def test_partition_writes_rollback_and_counters_rejected(self):
        for capability in ["USE_OTA_PARTITIONS", "USE_OTA_ROLLBACK", "USE_SAFE_MODE"]:
            with self.assertRaises(ValueError):
                audit_ota_defines("normal", DEFINES + "#define " + capability + "\n")
        for define in ["USE_OTA", "USE_OTA_PASSWORD", "USE_OTA_VERSION 2"]:
            with self.assertRaises(ValueError):
                audit_ota_defines(
                    "normal", DEFINES.replace("#define " + define + "\n", "")
                )
