"""Small user-session worker used by the elevated Windows service."""
import sys
import os
import tempfile
from pathlib import Path
from uuid import UUID


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        capture_id = UUID(sys.argv[1])
    except ValueError:
        return 2
    try:
        from PIL import Image, ImageGrab
    except ImportError:
        return 10
    try:
        image = ImageGrab.grab(all_screens=True)
        image.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
    except Exception:
        return 11
    output = Path(tempfile.gettempdir()) / f"LabGuard-{capture_id}.jpg"
    try:
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return 12
    except OSError:
        return 13
    try:
        with os.fdopen(descriptor, "wb") as stream:
            image.convert("RGB").save(stream, "JPEG", quality=65, optimize=True)
        return 0
    except Exception:
        output.unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
