"""Config flow (host + user RouterOS) + reauth + options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from yarl import URL

from . import build_api
from .api import RouterOSApiError, RouterOSAuthError
from .const import (
    CONF_BLOCK_PREFIX,
    CONF_KILL_CONNECTIONS,
    CONF_MONITOR_PORTS,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_BLOCK_PREFIX,
    DEFAULT_KILL_CONNECTIONS,
    DEFAULT_MONITOR_PORTS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def normalize_host(value: str) -> str:
    """Người dùng hay dán cả URL WebFig ("http://192.168.88.1/") → chỉ giữ host.

    Cổng trong URL bị bỏ: cổng có ô nhập riêng. IPv6 giữ ngoặc vuông để còn ghép URL.
    """
    value = value.strip()
    try:
        host = URL(value if "://" in value else f"http://{value}").host
    except ValueError:
        return value
    if not host:
        return value
    return f"[{host}]" if ":" in host else host


async def _validate(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[str | None, dict]:
    """Đăng nhập thử. Trả (error_key, info) — info có identity + unique id của router."""
    api = build_api(hass, data)
    try:
        identity = await api.get_dict("system/identity")
        # Đọc thử bảng filter: user thiếu quyền read sẽ lộ ra ngay ở bước này.
        await api.get_list("ip/firewall/filter", proplist=".id")
        board = await api.get_dict("system/routerboard")
        uid = board.get("serial-number")
        if not uid:  # CHR / x86 không có routerboard → dùng software-id của license
            lic = await api.get_dict("system/license")
            uid = lic.get("software-id") or lic.get("system-id")
    except RouterOSAuthError:
        return "invalid_auth", {}
    except RouterOSApiError:
        return "cannot_connect", {}
    except Exception:
        _LOGGER.exception("routeros: lỗi không xác định khi kết nối")
        return "unknown", {}
    return None, {"identity": identity.get("name") or data[CONF_HOST], "uid": uid}


USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_SSL, default=False): bool,
        vol.Required(CONF_VERIFY_SSL, default=False): bool,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class RouterOSConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = normalize_host(user_input[CONF_HOST])
            error, info = await _validate(self.hass, user_input)
            if error is None:
                await self.async_set_unique_id(
                    str(info["uid"] or user_input[CONF_HOST])
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["identity"], data=user_input)
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            error, _info = await _validate(self.hass, data)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RouterOSOptionsFlow()


class RouterOSOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_BLOCK_PREFIX,
                        default=opts.get(CONF_BLOCK_PREFIX, DEFAULT_BLOCK_PREFIX),
                    ): str,
                    vol.Required(
                        CONF_KILL_CONNECTIONS,
                        default=opts.get(
                            CONF_KILL_CONNECTIONS, DEFAULT_KILL_CONNECTIONS
                        ),
                    ): bool,
                    vol.Required(
                        CONF_MONITOR_PORTS,
                        default=opts.get(CONF_MONITOR_PORTS, DEFAULT_MONITOR_PORTS),
                    ): bool,
                }
            ),
        )
