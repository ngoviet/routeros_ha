"""Switch chặn thiết bị: 1 rule firewall filter (comment có tiền tố) = 1 switch.

Bật switch = bật rule drop = thiết bị MẤT mạng. Thêm rule mới trên router (đúng tiền tố
comment) là switch tự xuất hiện ở lần poll sau, không cần reload.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RouterOSConfigEntry
from .coordinator import BlockRule, RouterOSCoordinator
from .entity import RouterOSEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RouterOSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [k for k in coordinator.data.rules if k not in known]
        known.update(new)
        if new:
            async_add_entities(BlockSwitch(coordinator, k) for k in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BlockSwitch(RouterOSEntity, SwitchEntity):
    _attr_translation_key = "block"

    def __init__(self, coordinator: RouterOSCoordinator, key: str) -> None:
        super().__init__(coordinator, f"block_{key}")
        self._key = key
        self._attr_translation_placeholders = {
            "name": coordinator.data.rules[key].label
        }

    @property
    def rule(self) -> BlockRule | None:
        return self.coordinator.data.rules.get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self.rule is not None

    @property
    def is_on(self) -> bool | None:
        rule = self.rule
        return rule.enabled if rule else None

    @property
    def icon(self) -> str:
        return "mdi:web-off" if self.is_on else "mdi:web"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        rule = self.rule
        if rule is None:
            return None
        return {
            "src_address": rule.src_address,
            "comment": rule.comment,
            "rule_id": rule.rule_id,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_blocked(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_blocked(self._key, False)
