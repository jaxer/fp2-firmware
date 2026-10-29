"""Normal-only native OTA policy shared by build and offline audit."""

import re


def audit_ota_main(profile, main):
    components = re.findall(r"new\(\w+\) esphome::ESPHomeOTAComponent\(", main)
    if profile != "normal":
        if "OTAComponent" in main:
            raise ValueError("OTA is restricted to normal profile")
        return
    if (
        len(components) != 1
        or "new(normal_ota) esphome::ESPHomeOTAComponent(" not in main
    ):
        raise ValueError("normal requires exactly one native OTA component")
    if "normal_ota->set_port(3232);" not in main:
        raise ValueError("normal OTA port changed")
    if not re.search(r'normal_ota->set_auth_password\("[^"\n]+"\);', main):
        raise ValueError("normal OTA requires a nonempty password")
    if (
        "SafeModeComponent" in main
        or "WebServerOTAComponent" in main
        or "HttpRequestOTAComponent" in main
    ):
        raise ValueError("normal OTA recovery/download interface out of scope")


def audit_ota_defines(profile, defines):
    def enabled(name):
        return bool(re.search(r"^#define " + name + r"\b", defines, re.M))

    if profile == "normal":
        if not enabled("USE_OTA") or not enabled("USE_OTA_PASSWORD"):
            raise ValueError("normal native OTA/password support missing")
        if not re.search(r"^#define USE_OTA_VERSION 2$", defines, re.M):
            raise ValueError("normal OTA protocol must remain version2")
    elif enabled("USE_OTA"):
        raise ValueError("OTA is restricted to normal profile")
    for name in ["USE_OTA_PARTITIONS", "USE_OTA_ROLLBACK", "USE_SAFE_MODE"]:
        if enabled(name):
            raise ValueError("forbidden OTA capability " + name)
