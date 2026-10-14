"""Update entity CHỈ ĐỌC: RouterOS và firmware RouterBOARD.

Không có nút Install — cài RouterOS làm router khởi động lại (cả nhà mất mạng 1–2 phút),
không để một cú chạm nhầm trên dashboard hay automation làm việc đó.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RouterOSConfigEntry
from .api import as_bool
from .coordinator import RouterOSCoordinator
from .entity import RouterOSEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RouterOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[UpdateEntity] = [RouterOSUpdate(coordinator)]
    if as_bool((coordinator.data.routerboard or {}).get("routerboard")):
        entities.append(FirmwareUpdate(coordinator))
    async_add_entities(entities)


def _version(value: str | None) -> str | None:
    # resource.version = "7.24.4 (stable)" → "7.24.4"
    return value.split(" ")[0] if value else None


class RouterOSUpdate(RouterOSEntity, UpdateEntity):
    _attr_translation_key = "routeros"
    _attr_release_url = "https://mikrotik.com/download/changelogs"

    def __init__(self, coordinator: RouterOSCoordinator) -> None:
        super().__init__(coordinator, "routeros_update")

    @property
    def installed_version(self) -> str | None:
        pkg = self.coordinator.data.package_update or {}
        return pkg.get("installed-version") or _version(
            self.coordinator.data.resource.get("version")
        )

    @property
    def latest_version(self) -> str | None:
        pkg = self.coordinator.data.package_update or {}
        # Chưa từng check (hoặc router không ra được internet) → coi như đang mới nhất.
        return pkg.get("latest-version") or self.installed_version


class FirmwareUpdate(RouterOSEntity, UpdateEntity):
    """`upgrade-firmware` là bản firmware đi kèm RouterOS đang cài, chờ nâng cấp RouterBOOT."""

    _attr_translation_key = "firmware"

    def __init__(self, coordinator: RouterOSCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    @property
    def installed_version(self) -> str | None:
        return (self.coordinator.data.routerboard or {}).get("current-firmware")

    @property
    def latest_version(self) -> str | None:
        board = self.coordinator.data.routerboard or {}
        return board.get("upgrade-firmware") or board.get("current-firmware")
