"""Entity gốc: 1 router = 1 device."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import RouterOSCoordinator


class RouterOSEntity(CoordinatorEntity[RouterOSCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: RouterOSCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_{key}"
        res = coordinator.data.resource
        board = coordinator.data.routerboard or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            name=coordinator.identity,
            manufacturer=MANUFACTURER,
            model=res.get("board-name") or board.get("model"),
            serial_number=board.get("serial-number"),
            sw_version=res.get("version"),
            hw_version=board.get("revision"),
            configuration_url=f"http://{coordinator.api.host}",
        )
