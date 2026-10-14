"""Sensor: CPU / RAM / ổ nhớ / uptime / số thiết bị DHCP + sensor động từ /system/health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RouterOSConfigEntry
from .coordinator import RouterData, RouterOSCoordinator
from .entity import RouterOSEntity

PARALLEL_UPDATES = 0


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _used_pct(res: dict[str, Any], free: str, total: str) -> int | None:
    f, t = _num(res.get(free)), _num(res.get(total))
    if f is None or not t:
        return None
    return round((t - f) / t * 100)


@dataclass(frozen=True, kw_only=True)
class RouterSensorDescription(SensorEntityDescription):
    value_fn: Callable[[RouterData], Any]


SENSORS: tuple[RouterSensorDescription, ...] = (
    RouterSensorDescription(
        key="cpu_load",
        translation_key="cpu_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(d.resource.get("cpu-load")),
    ),
    RouterSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _used_pct(d.resource, "free-memory", "total-memory"),
    ),
    RouterSensorDescription(
        key="hdd_usage",
        translation_key="hdd_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _used_pct(d.resource, "free-hdd-space", "total-hdd-space"),
    ),
    RouterSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.boot_time,
    ),
    RouterSensorDescription(
        key="dhcp_clients",
        translation_key="dhcp_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.dhcp_bound,
    ),
)

# `type` của /system/health → (device_class, đơn vị HA)
HEALTH_UNITS: dict[str, tuple[SensorDeviceClass | None, str]] = {
    "C": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "RPM": (None, REVOLUTIONS_PER_MINUTE),
    "V": (SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
    "W": (SensorDeviceClass.POWER, UnitOfPower.WATT),
    "A": (SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE),
}
_UPPER = {"cpu": "CPU", "sfp": "SFP", "psu": "PSU", "poe": "PoE"}


def health_name(name: str) -> str:
    """ "cpu-temperature" → "CPU temperature", "board-temperature1" → "Board temperature1"."""
    words = [_UPPER.get(w, w) for w in name.split("-")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RouterOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(RouterSensor(coordinator, d) for d in SENSORS)

    known: set[str] = set()

    @callback
    def _add_health() -> None:
        new = [
            n
            for n, item in coordinator.data.health.items()
            if n not in known and item.unit in HEALTH_UNITS
        ]
        known.update(new)
        if new:
            async_add_entities(HealthSensor(coordinator, n) for n in new)

    _add_health()
    entry.async_on_unload(coordinator.async_add_listener(_add_health))


class RouterSensor(RouterOSEntity, SensorEntity):
    entity_description: RouterSensorDescription

    def __init__(
        self, coordinator: RouterOSCoordinator, description: RouterSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class HealthSensor(RouterOSEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RouterOSCoordinator, name: str) -> None:
        super().__init__(coordinator, f"health_{name}")
        self._health = name
        self._attr_name = health_name(name)
        unit = coordinator.data.health[name].unit
        device_class, native_unit = HEALTH_UNITS[unit]
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = native_unit
        if unit == "RPM":
            self._attr_icon = "mdi:fan"

    @property
    def available(self) -> bool:
        return super().available and self._health in self.coordinator.data.health

    @property
    def native_value(self) -> float | None:
        item = self.coordinator.data.health.get(self._health)
        return _num(item.value) if item else None
