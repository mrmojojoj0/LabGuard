from __future__ import annotations

import base64
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _protect(data: bytes, scope: str = "user") -> bytes:
    if platform.system() != "Windows":
        if os.getenv("LABGUARD_ALLOW_UNPROTECTED_DEV") == "1":
            return b"DEV:" + data
        raise RuntimeError("Device identity storage requires Windows DPAPI")
    import win32crypt

    flags = 0x4 if scope == "machine" else 0
    return win32crypt.CryptProtectData(data, "LabGuard device private key", None, None, None, flags)


def _unprotect(data: bytes) -> bytes:
    if data.startswith(b"DEV:") and os.getenv("LABGUARD_ALLOW_UNPROTECTED_DEV") == "1":
        return data[4:]
    if platform.system() != "Windows":
        raise RuntimeError("Device identity is protected by Windows DPAPI and can only be opened on Windows")
    import win32crypt

    return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]


@dataclass
class DeviceIdentity:
    device_id: str
    private_key: Ed25519PrivateKey
    state_file: Path | None = None
    sequence: int = 0
    protection_scope: str = "user"

    @classmethod
    def ephemeral(cls, device_id: str | None = None) -> "DeviceIdentity":
        return cls(device_id or str(uuid4()), Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, state_dir: Path) -> "DeviceIdentity":
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "identity.json"
        if state_file.exists():
            return cls._load_file(state_file)
        identity = cls(str(uuid4()), Ed25519PrivateKey.generate(), state_file)
        identity._save()
        return identity

    @classmethod
    def load_existing(cls, state_dir: Path) -> "DeviceIdentity":
        """Load identity without ever generating a replacement key or UUID."""
        state_file = state_dir / "identity.json"
        if not state_file.is_file():
            raise FileNotFoundError(f"Device identity not found: {state_file}")
        return cls._load_file(state_file)

    @classmethod
    def _load_file(cls, state_file: Path) -> "DeviceIdentity":
        record = json.loads(state_file.read_text(encoding="utf-8"))
        scope = record.get("protection_scope", "user")
        if scope not in {"user", "machine"}:
            raise RuntimeError("Stored identity has an unknown DPAPI protection scope")
        private_bytes = _unprotect(base64.b64decode(record["private_key_protected"]))
        key = serialization.load_pem_private_key(private_bytes, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("Stored identity key is not Ed25519")
        return cls(record["device_id"], key, state_file, int(record.get("sequence", 0)), scope)

    def public_key_pem(self) -> str:
        return self.private_key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")

    def next_sequence(self) -> int:
        self.sequence += 1
        if self.state_file:
            self._save()
        return self.sequence

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)

    def _save(self):
        assert self.state_file is not None
        private_bytes = self.private_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        protected = base64.b64encode(_protect(private_bytes, self.protection_scope)).decode("ascii")
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps({"device_id": self.device_id, "private_key_protected": protected,
                                    "sequence": self.sequence, "protection_scope": self.protection_scope}, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, self.state_file)
