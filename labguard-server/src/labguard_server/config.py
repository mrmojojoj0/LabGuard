from dataclasses import dataclass
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    session_secret: str | None
    cookie_secure: bool = True
    session_ttl_hours: int = 8
    enrollment_code_ttl_minutes: int = 15
    app_env: str = "production"
    log_level: str = "INFO"
    heartbeat_interval_seconds: float = 10.0
    delayed_after_seconds: float = 30.0
    offline_after_seconds: float = 60.0
    device_challenge_ttl_seconds: int = 30
    device_ticket_ttl_seconds: int = 30
    telemetry_retention_days: int = 30
    telemetry_stale_after_seconds: int = 120
    telemetry_min_interval_seconds: float = 10.0
    software_inventory_refresh_cooldown_seconds: int = 300
    software_inventory_min_interval_seconds: float = 10.0
    software_inventory_stale_after_seconds: int = 604800
    software_inventory_retention_days: int = 90
    chocolatey_source_url: str | None = None
    software_job_max_runtime_seconds: int = 1800
    ipinfo_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            session_secret=os.getenv("SESSION_SECRET"),
            cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
            session_ttl_hours=int(os.getenv("SESSION_TTL_HOURS", "8")),
            enrollment_code_ttl_minutes=int(os.getenv("ENROLLMENT_CODE_TTL_MINUTES", "15")),
            app_env=os.getenv("APP_ENV", "production"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            heartbeat_interval_seconds=float(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "10")),
            delayed_after_seconds=float(os.getenv("DEVICE_DELAYED_AFTER_SECONDS", "30")),
            offline_after_seconds=float(os.getenv("DEVICE_OFFLINE_AFTER_SECONDS", "60")),
            device_challenge_ttl_seconds=int(os.getenv("DEVICE_CHALLENGE_TTL_SECONDS", "30")),
            device_ticket_ttl_seconds=int(os.getenv("DEVICE_TICKET_TTL_SECONDS", "30")),
            telemetry_retention_days=int(os.getenv("TELEMETRY_RETENTION_DAYS", "30")),
            telemetry_stale_after_seconds=int(os.getenv("TELEMETRY_STALE_AFTER_SECONDS", "120")),
            telemetry_min_interval_seconds=float(os.getenv("TELEMETRY_MIN_INTERVAL_SECONDS", "10")),
            software_inventory_refresh_cooldown_seconds=int(os.getenv("SOFTWARE_INVENTORY_REFRESH_COOLDOWN_SECONDS", "300")),
            software_inventory_min_interval_seconds=float(os.getenv("SOFTWARE_INVENTORY_MIN_INTERVAL_SECONDS", "10")),
            software_inventory_stale_after_seconds=int(os.getenv("SOFTWARE_INVENTORY_STALE_AFTER_SECONDS", "604800")),
            software_inventory_retention_days=int(os.getenv("SOFTWARE_INVENTORY_RETENTION_DAYS", "90")),
            chocolatey_source_url=os.getenv("CHOCOLATEY_SOURCE_URL") or None,
            software_job_max_runtime_seconds=int(os.getenv("SOFTWARE_JOB_MAX_RUNTIME_SECONDS", "1800")),
            ipinfo_token=os.getenv("IPINFO_TOKEN") or None,
        )

    def validate(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL must be configured")
        if not self.session_secret or len(self.session_secret) < 32:
            raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
        if self.session_ttl_hours < 1 or self.enrollment_code_ttl_minutes < 1:
            raise RuntimeError("Session and enrollment expiration values must be positive")
        if not (0 < self.heartbeat_interval_seconds < self.delayed_after_seconds < self.offline_after_seconds):
            raise RuntimeError("Require 0 < heartbeat interval < delayed threshold < offline threshold")
        if self.device_challenge_ttl_seconds < 1 or self.device_ticket_ttl_seconds < 1:
            raise RuntimeError("Device challenge and ticket TTLs must be positive")
        if not (1 <= self.telemetry_retention_days <= 3650 and 1 <= self.telemetry_stale_after_seconds <= 86400
                and 1 <= self.telemetry_min_interval_seconds <= 3600):
            raise RuntimeError("Telemetry retention, stale threshold, and minimum interval are outside supported bounds")
        if not (30 <= self.software_inventory_refresh_cooldown_seconds <= 86400
                and 1 <= self.software_inventory_min_interval_seconds <= 60
                and 3600 <= self.software_inventory_stale_after_seconds <= 2_592_000
                and 1 <= self.software_inventory_retention_days <= 3650):
            raise RuntimeError("Software inventory cooldown, stale threshold, and retention are outside supported bounds")
        if not 60 <= self.software_job_max_runtime_seconds <= 7200:
            raise RuntimeError("Software job timeout must be between 60 and 7200 seconds")
        if self.chocolatey_source_url:
            parsed = urlsplit(self.chocolatey_source_url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise RuntimeError("CHOCOLATEY_SOURCE_URL must be an HTTP or HTTPS URL without credentials, query, or fragment")
