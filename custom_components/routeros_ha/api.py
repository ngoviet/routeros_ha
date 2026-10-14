"""Client REST cho RouterOS 7 (`http(s)://<router>/rest/...`).

Đặc điểm REST của RouterOS (đo thật trên 7.24.4):

- Xác thực Basic auth mỗi request; user cần policy `rest-api` (+ `read`, và `write` để ghi).
- MỌI giá trị trả về là CHUỖI, kể cả boolean ("true"/"false") và số.
- Menu singleton (`/system/resource`, `/system/identity`, ...) trả dict, menu danh sách trả list.
- GET nhận `?.proplist=a,b` để chỉ lấy vài cột và `?<prop>=<value>` để lọc bằng đúng giá trị.
- Lỗi trả JSON `{"error": 400, "message": "Bad Request", "detail": "..."}`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class RouterOSApiError(Exception):
    """Lỗi mạng / router trả lỗi."""


class RouterOSAuthError(RouterOSApiError):
    """Sai user/mật khẩu, hoặc user không có policy `rest-api`."""


def as_bool(value: Any) -> bool:
    """REST trả "true"/"false" dạng chuỗi — `bool("false")` là True nên phải so chuỗi."""
    return str(value).strip().lower() in ("true", "yes")


class RouterOSApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = False,
        verify_ssl: bool = False,
    ) -> None:
        self._session = session
        scheme = "https" if use_ssl else "http"
        self.host = host
        # WebFig chạy trên cùng service www/www-ssl với REST → dùng làm configuration_url.
        default_port = 443 if use_ssl else 80
        self.web_url = f"{scheme}://{host}" + (
            "" if port == default_port else f":{port}"
        )
        self._base = f"{scheme}://{host}:{port}/rest/"
        self._auth = aiohttp.BasicAuth(username, password)
        self._ssl: bool | None = None if (not use_ssl or verify_ssl) else False

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._base + path
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=body,
                auth=self._auth,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise RouterOSAuthError(f"{method} {path}: 401 Unauthorized")
                if resp.status >= 400:
                    raise RouterOSApiError(
                        f"{method} {path}: HTTP {resp.status} {_error_detail(text)}"
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RouterOSApiError(f"{method} {path}: {err!r}") from err
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            raise RouterOSApiError(f"{method} {path}: JSON hỏng: {text[:120]}") from err

    async def get(
        self, path: str, *, proplist: str | None = None, **filters: str
    ) -> Any:
        params = dict(filters)
        if proplist:
            params[".proplist"] = proplist
        return await self._request("GET", path, params=params or None)

    async def get_dict(self, path: str, **kwargs: Any) -> dict[str, Any]:
        data = await self.get(path, **kwargs)
        if isinstance(data, list):  # phòng khi menu trả 1 phần tử dạng list
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}

    async def get_list(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        data = await self.get(path, **kwargs)
        if isinstance(data, dict):
            return [data]
        return [x for x in data or [] if isinstance(x, dict)]

    async def patch(self, path: str, body: dict[str, Any]) -> Any:
        return await self._request("PATCH", path, body=body)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, body=body or {})

    async def delete(self, path: str) -> None:
        await self._request("DELETE", path)

    # --- thao tác cụ thể -------------------------------------------------

    async def set_filter_disabled(self, rule_id: str, disabled: bool) -> None:
        await self.patch(
            f"ip/firewall/filter/{rule_id}",
            {"disabled": "true" if disabled else "false"},
        )

    async def remove_connections_from(self, ip: str, concurrency: int) -> int:
        """Xoá mọi dòng connection-tracking có nguồn là `ip`. Trả số dòng đã xoá.

        Bảng connection chỉ vài nghìn dòng → đọc 2 cột rồi lọc phía client, tránh
        phải ghép regex vào script RouterOS. `src-address` có dạng "ip:port" (TCP/UDP)
        hoặc "ip" (ICMP...).
        """
        conns = await self.get_list(
            "ip/firewall/connection", proplist=".id,src-address"
        )
        ids = [
            c[".id"]
            for c in conns
            if ".id" in c and str(c.get("src-address", "")).split(":")[0] == ip
        ]
        sem = asyncio.Semaphore(concurrency)

        async def _drop(conn_id: str) -> bool:
            async with sem:
                try:
                    await self.delete(f"ip/firewall/connection/{conn_id}")
                except RouterOSApiError as err:
                    # Connection có thể đã tự đóng giữa lúc đọc và xoá → không phải lỗi.
                    _LOGGER.debug("routeros: xoá connection %s lỗi: %s", conn_id, err)
                    return False
                return True

        results = await asyncio.gather(*(_drop(i) for i in ids))
        return sum(results)


def _error_detail(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return text[:200]
    if isinstance(data, dict):
        return " — ".join(str(data[k]) for k in ("message", "detail") if data.get(k))
    return text[:200]
