"""FP2 diagnostics and opt-in allowlisted occupancy queries/ACKs."""

import esphome.codegen as cg
import esphome.config_validation as cv
import esphome.final_validate as fv
from esphome.core import CORE
from esphome.components import binary_sensor, sensor, text_sensor, uart, i2c
from esphome.const import (
    CONF_ID,
    DEVICE_CLASS_OCCUPANCY,
    CONF_TX_PIN,
    CONF_UART_ID,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_TOTAL_INCREASING,
    STATE_CLASS_MEASUREMENT,
    DEVICE_CLASS_ILLUMINANCE,
    UNIT_LUX,
)

DEPENDENCIES = ["uart"]
AUTO_LOAD = ["sensor", "text_sensor", "binary_sensor"]

fp2_ns = cg.esphome_ns.namespace("fp2")
FP2Component = fp2_ns.class_("FP2Component", cg.Component, uart.UARTDevice)
COUNTERS = ("received_valid_frames", "rejected_frames", "bytes_received")


def unique_zones(config):
    if ("illuminance" in config) != ("light_i2c_id" in config):
        raise cv.Invalid("illuminance and light_i2c_id must be configured together")
    ids = [zone["zone_id"] for zone in config.get("zones", [])]
    native_ids = [zone["zone_id"] for zone in config.get("native_zones", [])]
    if len(native_ids) != len(set(native_ids)):
        raise cv.Invalid("Each fp2 native zone_id must be unique")
    if len(ids) != len(set(ids)):
        raise cv.Invalid("Each fp2 zone_id must be unique")
    if config.get("enable_native_snapshot", False) and not config.get(
        "allow_tx", False
    ):
        raise cv.Invalid("enable_native_snapshot requires allow_tx")
    if config.get("allow_configuration", False) and not config.get("allow_tx", False):
        raise cv.Invalid("allow_configuration requires allow_tx")
    if config.get("enable_target_events", False) and not config.get(
        "enable_target_reports", False
    ):
        raise cv.Invalid("enable_target_events requires enable_target_reports")
    if config.get("enable_target_reports", False) and not config.get("allow_tx", False):
        raise cv.Invalid("enable_target_reports requires allow_tx")
    if config.get("enable_orientation", False) and "orientation_i2c_id" not in config:
        raise cv.Invalid("enable_orientation requires orientation_i2c_id")
    if not config.get("enable_orientation", False) and "orientation_i2c_id" in config:
        raise cv.Invalid("orientation_i2c_id requires enable_orientation")
    if config.get("orientation_native_i2c", False) and not config.get(
        "enable_orientation", False
    ):
        raise cv.Invalid("orientation_native_i2c requires enable_orientation")
    return config


def grid_hex(value):
    value = cv.string_strict(value)
    if len(value) != 80 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise cv.Invalid(
            "grid must contain exactly 80 hexadecimal characters (40 bytes)"
        )
    return value.lower()


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(FP2Component),
            cv.Optional("allow_tx", default=False): cv.boolean,
            cv.Optional("enable_native_snapshot", default=False): cv.boolean,
            cv.Optional("allow_configuration", default=False): cv.boolean,
            cv.Optional("enable_target_reports", default=False): cv.boolean,
            cv.Optional("enable_target_events", default=False): cv.boolean,
            cv.Optional("enable_orientation", default=False): cv.boolean,
            cv.Optional("orientation_native_i2c", default=False): cv.boolean,
            cv.Optional("orientation_i2c_id"): cv.use_id(i2c.I2CBus),
            cv.Optional("light_i2c_id"): cv.use_id(i2c.I2CBus),
            cv.Optional("target_count"): sensor.sensor_schema(accuracy_decimals=0),
            cv.Optional("measured_tilt"): sensor.sensor_schema(
                accuracy_decimals=0,
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
                unit_of_measurement="°",
            ).extend({cv.Optional("disabled_by_default", default=True): cv.boolean}),
            cv.Optional("mounting_direction"): sensor.sensor_schema(
                accuracy_decimals=0, entity_category=ENTITY_CATEGORY_DIAGNOSTIC
            ).extend({cv.Optional("disabled_by_default", default=True): cv.boolean}),
            cv.Optional("orientation_read_failures"): sensor.sensor_schema(
                accuracy_decimals=0, entity_category=ENTITY_CATEGORY_DIAGNOSTIC
            ).extend({cv.Optional("disabled_by_default", default=True): cv.boolean}),
            cv.Optional("illuminance"): sensor.sensor_schema(
                accuracy_decimals=0,
                device_class=DEVICE_CLASS_ILLUMINANCE,
                state_class=STATE_CLASS_MEASUREMENT,
                unit_of_measurement=UNIT_LUX,
            ),
            cv.Optional(
                "stale_timeout", default="90s"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(
                "diagnostic_interval", default="1s"
            ): cv.positive_time_period_milliseconds,
            cv.Optional("query_interval", default="10s"): cv.All(
                cv.positive_time_period_milliseconds,
                cv.Range(min=cv.TimePeriod(milliseconds=50)),
            ),
            cv.Optional("presence"): binary_sensor.binary_sensor_schema(
                device_class=DEVICE_CLASS_OCCUPANCY,
            ),
            cv.Optional("radar_configuration"): text_sensor.text_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC
            ),
            cv.Optional("learning_status"): text_sensor.text_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC
            ),
            cv.Optional("auto_edge_candidate"): text_sensor.text_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC
            ),
            cv.Optional("configuration_status"): text_sensor.text_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            ),
            cv.Optional("native_zones", default=[]): cv.ensure_list(
                binary_sensor.binary_sensor_schema(
                    device_class=DEVICE_CLASS_OCCUPANCY
                ).extend({cv.Required("zone_id"): cv.int_range(min=1, max=30)})
            ),
            cv.Optional("zones", default=[]): cv.ensure_list(
                binary_sensor.binary_sensor_schema(
                    device_class=DEVICE_CLASS_OCCUPANCY
                ).extend(
                    {
                        cv.Required("zone_id"): cv.int_range(min=1, max=30),
                        cv.Optional("grid"): grid_hex,
                    }
                )
            ),
            **{
                cv.Optional(key): sensor.sensor_schema(
                    accuracy_decimals=0,
                    entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
                    state_class=STATE_CLASS_TOTAL_INCREASING,
                )
                for key in COUNTERS
            },
            cv.Optional("last_report"): text_sensor.text_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            ),
            cv.Optional("radar_traffic"): binary_sensor.binary_sensor_schema(
                entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            ),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .extend(uart.UART_DEVICE_SCHEMA),
    unique_zones,
)


def reject_tx(hub_config):
    if CONF_TX_PIN in hub_config:
        raise cv.Invalid("fp2 is RX-only: remove tx_pin from its UART bus")
    return hub_config


def final_validate(config):
    # UART's validator returns a copy with uart_id replaced by the resolved hub.
    # Keep that result out of the component config: code generation needs its ID.
    full_config = fv.full_config.get()
    if config["enable_target_events"]:
        api_config = full_config.get("api")
        if not api_config or not api_config.get("homeassistant_services", False):
            raise cv.Invalid(
                "enable_target_events requires api.homeassistant_services: true"
            )
    if config["orientation_native_i2c"]:
        if not CORE.is_esp32:
            raise cv.Invalid("orientation_native_i2c requires ESP32")
        bus_path = full_config.get_path_for_id(config["orientation_i2c_id"])[:-1]
        bus_config = full_config.get_config_for_path(bus_path)
        if not bus_config[CONF_ID].type.inherits_from(i2c.InternalI2CBus):
            raise cv.Invalid("orientation_native_i2c requires an internal I2C bus")
    hub_path = full_config.get_path_for_id(config[CONF_UART_ID])[:-1]
    hub_config = full_config.get_config_for_path(hub_path)
    with cv.prepend_path([cv.ROOT_CONFIG_PATH] + hub_path):
        if not config["allow_tx"]:
            reject_tx(hub_config)
        elif CONF_TX_PIN not in hub_config:
            raise cv.Invalid("fp2 allow_tx requires a UART tx_pin")
    uart.final_validate_device_schema(
        "fp2", require_rx=True, data_bits=8, parity="NONE", stop_bits=1
    )(dict(config))
    return config


FINAL_VALIDATE_SCHEMA = final_validate


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    cg.add(
        var.set_diagnostic_interval(config["diagnostic_interval"].total_milliseconds)
    )
    await cg.register_component(var, config)
    await uart.register_uart_device(var, config)
    for key in (
        "target_count",
        "measured_tilt",
        "mounting_direction",
        "orientation_read_failures",
    ):
        if key in config:
            entity = await sensor.new_sensor(config[key])
            cg.add(getattr(var, f"set_{key}")(entity))
    if "illuminance" in config:
        cg.add_define("USE_FP2_LIGHT")
        bus = await cg.get_variable(config["light_i2c_id"])
        cg.add(var.set_light_i2c_bus(bus))
        entity = await sensor.new_sensor(config["illuminance"])
        cg.add(var.set_illuminance(entity))
    cg.add(var.set_allow_tx(config["allow_tx"]))
    cg.add(var.set_enable_native_snapshot(config["enable_native_snapshot"]))
    cg.add(var.set_allow_configuration(config["allow_configuration"]))
    cg.add(var.set_enable_orientation(config["enable_orientation"]))
    if config["enable_orientation"]:
        cg.add_define("USE_FP2_ORIENTATION")
        bus = await cg.get_variable(config["orientation_i2c_id"])
        cg.add(var.set_orientation_i2c_bus(bus))
        if config["orientation_native_i2c"]:
            bus_config = next(
                entry
                for entry in CORE.config["i2c"]
                if str(entry[CONF_ID]) == str(config["orientation_i2c_id"])
            )
            cg.add(var.set_orientation_native_i2c(bus, bus_config["frequency"]))
    cg.add(var.set_enable_target_reports(config["enable_target_reports"]))
    cg.add(var.set_enable_target_events(config["enable_target_events"]))
    if config["enable_target_events"]:
        cg.add_define("USE_FP2_TARGET_EVENTS")
    cg.add(var.set_stale_timeout(config["stale_timeout"].total_milliseconds))
    cg.add(var.set_query_interval(config["query_interval"].total_milliseconds))
    if "presence" in config:
        entity = await binary_sensor.new_binary_sensor(config["presence"])
        cg.add(var.set_presence(entity))
    for key in ("learning_status", "auto_edge_candidate", "radar_configuration"):
        if key in config:
            entity = await text_sensor.new_text_sensor(config[key])
            cg.add(getattr(var, f"set_{key}")(entity))
    if "configuration_status" in config:
        entity = await text_sensor.new_text_sensor(config["configuration_status"])
        cg.add(var.set_configuration_status(entity))
    for zone in config["native_zones"]:
        entity = await binary_sensor.new_binary_sensor(zone)
        cg.add(var.add_native_zone(zone["zone_id"], entity))
    for zone in config["zones"]:
        entity = await binary_sensor.new_binary_sensor(zone)
        cg.add(var.add_zone(zone["zone_id"], entity))
        if "grid" in zone:
            cg.add(
                var.set_zone_grid(zone["zone_id"], list(bytes.fromhex(zone["grid"])))
            )
    for key in COUNTERS:
        if key in config:
            entity = await sensor.new_sensor(config[key])
            cg.add(getattr(var, f"set_{key}")(entity))
    if "last_report" in config:
        entity = await text_sensor.new_text_sensor(config["last_report"])
        cg.add(var.set_last_report(entity))
    if "radar_traffic" in config:
        entity = await binary_sensor.new_binary_sensor(config["radar_traffic"])
        cg.add(var.set_radar_traffic(entity))
