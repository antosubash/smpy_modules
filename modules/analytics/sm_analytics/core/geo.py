"""Local GeoIP resolution; raw addresses never leave this call."""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Location:
    country: str = ""
    country_name: str = ""
    region: str = ""
    region_name: str = ""
    city: str = ""
    city_name: str = ""

    def fields(self) -> dict[str, str]:
        return asdict(self)


def _reader(path: str) -> Any:
    from geoip2.database import Reader

    return Reader(path)


class GeoResolver:
    def __init__(self, path: str = "", enabled: bool = False, reader_factory: Any = _reader):
        self.path = path
        self.enabled = enabled
        self._factory = reader_factory
        self._reader: Any = None
        self._signature: tuple | None = None
        self._failed: tuple | None = None
        self._status = "disabled"
        self._age: int | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        if not self.enabled:
            self._close()
            self._status = "disabled"
            return
        signature = None
        try:
            stat = Path(self.path).stat() if self.path else None
            if stat is None:
                raise FileNotFoundError
            signature = (self.path, stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if signature == self._failed:
                self._status = "unavailable"
                return
            if self._reader is not None and signature == self._signature:
                return
            self._close()
            self._reader = self._factory(self.path)
            self._signature = signature
            self._failed = None
            self._age = max(0, int((time.time() - self._reader.metadata().build_epoch) / 86400))
            self._status = "stale" if self._age > 30 else "ready"
        except Exception:
            # No addresses or filenames in logs: the status screen explains provisioning.
            if self._status != "unavailable":
                logger.warning("Analytics geolocation unavailable; collecting unknown locations")
            self._close()
            self._failed = signature
            self._status = "unavailable"

    def lookup(self, ip: str) -> Location:
        try:
            if not ipaddress.ip_address(ip).is_global:
                return Location()
        except ValueError:
            return Location()
        with self._lock:
            self._refresh()
            if self._reader is None:
                return Location()
            try:
                result = self._reader.city(ip)
                country = result.country.iso_code or ""
                subdivision = result.subdivisions.most_specific
                region = (
                    f"{country}-{subdivision.iso_code}" if country and subdivision.iso_code else ""
                )
                return Location(
                    country,
                    result.country.name or "",
                    region,
                    subdivision.name or "",
                    str(result.city.geoname_id or ""),
                    result.city.name or "",
                )
            except Exception as exc:
                # The optional reader's normal no-match exception leaves the database healthy.
                if type(exc).__name__ != "AddressNotFoundError":
                    signature = self._signature
                    self._close()
                    self._failed = signature
                    self._status = "unavailable"
                    logger.warning(
                        "Analytics geolocation lookup failed; collecting unknown locations"
                    )
                return Location()

    def status(self) -> dict:
        with self._lock:
            self._refresh()
            return {
                "enabled": self.enabled,
                "available": self._reader is not None,
                "status": self._status,
                "age_days": self._age,
            }

    def _close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        self._reader = None
        self._signature = None
        self._age = None

    def close(self) -> None:
        with self._lock:
            self._close()
