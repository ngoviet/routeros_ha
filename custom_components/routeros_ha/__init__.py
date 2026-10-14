"""RouterOS (MikroTik) — chặn/bỏ chặn thiết bị bằng rule firewall + giám sát router qua REST API."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RouterOSApi
from .const import (
    CONF_BLOCK_PREFIX,
    CONF_KILL_CONNECTIONS,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_BLOCK_PREFIX,
    DEFAULT_KILL_CONNECTIONS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import RouterOSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

type RouterOSConfigEntry = ConfigEntry[RouterOSCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def build_api(hass: HomeAssistant, data: dict) -> RouterOSApi:
    return RouterOSApi(
        async_get_clientsession(hass, verify_ssl=data.get(CONF_VERIFY_SSL, False)),
        data[CONF_HOST],
        int(data.get(CONF_PORT, DEFAULT_PORT)),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        use_ssl=data.get(CONF_SSL, False),
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )


async def async_setup_entry(hass: HomeAssistant, entry: RouterOSConfigEntry) -> bool:
    opts = entry.options
    coordinator = RouterOSCoordinator(
        hass,
        build_api(hass, dict(entry.data)),
        entry,
        int(opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        opts.get(CONF_BLOCK_PREFIX, DEFAULT_BLOCK_PREFIX),
        opts.get(CONF_KILL_CONNECTIONS, DEFAULT_KILL_CONNECTIONS),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info(
        "RouterOS %s ready: %d rule chặn %s",
        coordinator.identity,
        len(coordinator.data.rules),
        list(coordinator.data.rules),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RouterOSConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: RouterOSConfigEntry
) -> None:
    """Đổi options → reload entry (không cần restart HA)."""
    await hass.config_entries.async_reload(entry.entry_id)
