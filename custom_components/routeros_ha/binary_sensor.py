"""Binary sensor sự cố từ /system/health dạng trạng thái (fan-state, psu1-state, ...).

`on` = có sự cố (giá trị khác "ok"). Ví dụ CCR2004 chỉ cắm 1 nguồn → psu2-state = "fail".
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RouterOSConfigEntry
from .coordinator import RouterOSCoordinator
from .entity import RouterOSEntity
from .sensor import health_name

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RouterOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [
            n
            for n, item in coordinator.data.health.items()
            if n not in known and n.endswith("-state")
        ]
        known.update(new)
        if new:
            async_add_entities(HealthProblem(coordinator, n) for n in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class HealthProblem(RouterOSEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RouterOSCoordinator, name: str) -> None:
        super().__init__(coordinator, f"health_{name}")
        self._health = name
        self._attr_name = health_name(name.removesuffix("-state"))

    @property
    def available(self) -> bool:
        return super().available and self._health in self.coordinator.data.health

    @property
    def is_on(self) -> bool | None:
        item = self.coordinator.data.health.get(self._health)
        return None if item is None else item.value.strip().lower() != "ok"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        item = self.coordinator.data.health.get(self._health)
        return {"value": item.value} if item else None
