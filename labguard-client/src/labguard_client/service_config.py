from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AgentConfig:
    server_url: str
    state_dir: Path
    timeout: float = 15.0
    telemetry_interval_seconds: float = 30.0
    software_inventory_interval_seconds: float = 6 * 60 * 60

    def __post_init__(self):
        parsed = urlsplit(self.server_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Service server_url must be an HTTPS URL without embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Service server_url cannot include a query or fragment")
        if not self.state_dir.is_absolute():
            raise ValueError("Service state_dir must be an absolute path")
        if not 1 <= self.timeout <= 120:
            raise ValueError("timeout must be between 1 and 120 seconds")
        if not 10 <= self.telemetry_interval_seconds <= 3600:
            raise ValueError("telemetry_interval_seconds must be between 10 and 3600")
        if not 300 <= self.software_inventory_interval_seconds <= 604800:
            raise ValueError("software_inventory_interval_seconds must be between 300 and 604800")

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data["server_url"], Path(data["state_dir"]), float(data.get("timeout", 15)),
                       float(data.get("telemetry_interval_seconds", 30)),
                       float(data.get("software_inventory_interval_seconds", 21600)))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid LabGuard service configuration: {type(exc).__name__}") from exc

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"server_url": self.server_url, "state_dir": str(self.state_dir),
            "timeout": self.timeout, "telemetry_interval_seconds": self.telemetry_interval_seconds,
            "software_inventory_interval_seconds": self.software_inventory_interval_seconds}, indent=2), encoding="utf-8")
        temp.replace(path)
