from dataclasses import dataclass
import os


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
