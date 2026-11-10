from __future__ import annotations

from ipaddress import ip_address
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import threading
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.models import Device, DeviceTelemetryLatest

_CACHE_TTL_SECONDS = 6 * 60 * 60
_ERROR_CACHE_TTL_SECONDS = 60
_MAX_LOOKUPS_PER_RESPONSE = 40
_MAX_CONNECTIONS_PER_RESPONSE = 200
_cache_lock = threading.Lock()
_ipinfo_cache: dict[str, tuple[float, dict | None]] = {}
_logger = logging.getLogger("labguard_server.network_activity")


def network_activity(db: Session, ipinfo_token: str | None) -> dict:
    pairs = db.execute(
        select(Device, DeviceTelemetryLatest)
        .join(DeviceTelemetryLatest, DeviceTelemetryLatest.device_id == Device.id)
    ).all()
    records = []
    for device, latest in pairs:
        for connection in latest.network_connections or []:
            remote_ip = connection.get("remote_ip")
            if not isinstance(remote_ip, str) or not _is_public_ip(remote_ip):
                continue
            records.append({
                "device_id": str(device.id),
                "device_name": device.assigned_name or device.hostname,
                "observed_at": connection.get("observed_at"),
                "direction": connection.get("direction"),
                "protocol": connection.get("protocol"),
                "remote_ip": remote_ip,
                "remote_port": connection.get("remote_port"),
                "local_port": connection.get("local_port"),
                "interface": connection.get("interface"),
                "state": connection.get("state"),
            })
    records.sort(key=lambda item: item["observed_at"] or "", reverse=True)
    records = records[:_MAX_CONNECTIONS_PER_RESPONSE]

    organizations: dict[str, dict | None] = {}
    if ipinfo_token:
        addresses = list(dict.fromkeys(item["remote_ip"] for item in records))[:_MAX_LOOKUPS_PER_RESPONSE]
        with ThreadPoolExecutor(max_workers=20) as pool:
            organizations.update(zip(addresses, pool.map(
                lambda address: _lookup_ipinfo(address, ipinfo_token), addresses)))

    for item in records:
        item["organization"] = organizations.get(item["remote_ip"])
    return {
        "connections": records,
        "lookups_enabled": bool(ipinfo_token),
        "public_ip_count": len({item["remote_ip"] for item in records}),
    }


def _is_public_ip(value: str) -> bool:
    try:
        return ip_address(value).is_global
    except ValueError:
        return False


def _lookup_ipinfo(address: str, token: str) -> dict | None:
    now = monotonic()
    with _cache_lock:
        cached = _ipinfo_cache.get(address)
        if cached is not None and cached[0] > now:
            return cached[1]

    url = f"https://api.ipinfo.io/lite/{quote(address, safe=':')}"
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    value = None
    ttl = _ERROR_CACHE_TTL_SECONDS
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(8192))
        if (isinstance(payload, dict) and isinstance(payload.get("ip"), str)
                and ip_address(payload["ip"]) == ip_address(address)):
            value = {
                "asn": payload.get("asn"),
                "as_name": payload.get("as_name"),
                "as_domain": payload.get("as_domain"),
                "country": payload.get("country"),
                "country_code": payload.get("country_code"),
            }
            ttl = _CACHE_TTL_SECONDS
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        _logger.warning("IPinfo lookup failed for a public address (%s)", type(exc).__name__)

    with _cache_lock:
        if len(_ipinfo_cache) >= 4096:
            expired = [key for key, (expiry, _) in _ipinfo_cache.items() if expiry <= now]
            for key in expired:
                _ipinfo_cache.pop(key, None)
            if len(_ipinfo_cache) >= 4096:
                _ipinfo_cache.pop(next(iter(_ipinfo_cache)))
        _ipinfo_cache[address] = (now + ttl, value)
    return value
