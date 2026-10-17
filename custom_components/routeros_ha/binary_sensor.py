"""Binary sensor: sự cố từ /system/health + link từng cổng ethernet.

Health dạng trạng thái (fan-state, psu1-state, ...): `on` = có sự cố (giá trị khác "ok").
Ví dụ CCR2004 chỉ cắm 1 nguồn → psu2-state = "fail".
Link cổng: `on` = cổng có link (`running`), thuộc tính kèm tốc độ link.
"""

from __future__ import annotations

from typing import Any

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

    known_ports: set[str] = set()

    @callback
    def _add_ports() -> None:
        new = [k for k in coordinator.data.ports or {} if k not in known_ports]
        known_ports.update(new)
        if new:
            async_add_entities(PortLink(coordinator, k) for k in new)

    _add_ports()
    entry.async_on_unload(coordinator.async_add_listener(_add_ports))


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


class PortLink(RouterOSEntity, BinarySensorEntity):
    """Link của 1 cổng ethernet / SFP. Chỉ đọc — không có thao tác bật/tắt cổng."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "port_link"

    def __init__(self, coordinator: RouterOSCoordinator, key: str) -> None:
        super().__init__(coordinator, f"port_{key}_link")
        self._key = key
        self._attr_translation_placeholders = {"port": coordinator.data.ports[key].name}

    @property
    def available(self) -> bool:
        return super().available and self._key in (self.coordinator.data.ports or {})

    @property
    def is_on(self) -> bool | None:
        port = (self.coordinator.data.ports or {}).get(self._key)
        return None if port is None else port.running

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        port = (self.coordinator.data.ports or {}).get(self._key)
        if port is None:
            return None
        return {
            "port": port.name,
            "default_name": port.default_name,
            "comment": port.comment,
            "rate": port.rate,
            "speed_mbps": port.speed_mbps,
            "disabled": port.disabled,
            "link_downs": port.link_downs,
            "mac_address": port.mac_address,
            # Thiết bị đang cắm: LLDP neighbor hoặc DHCP lease (comment) — card sơ đồ mạng
            # dùng làm tên cổng.
            "device": port.device.name if port.device else None,
            "device_ip": port.device.ip if port.device else None,
            "device_mac": port.device.mac if port.device else None,
            "device_source": port.device.source if port.device else None,
        }
