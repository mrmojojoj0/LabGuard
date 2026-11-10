from __future__ import annotations

import hashlib
import logging
import platform
import re


def collect_peripherals() -> list[dict] | None:
    """Collect a bounded snapshot of attached external peripherals on Windows.

    Only device names, broad classes and a one-way PnP identifier hash leave the
    endpoint. The PnP identifier itself can contain a hardware serial number and
    is never transmitted.
    """
    if platform.system() != "Windows":
        return None
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None

    pythoncom.CoInitialize()
    try:
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        services = locator.ConnectServer(".", "root\\cimv2")
        found: dict[str, dict] = {}

        drives = services.ExecQuery(
            "SELECT PNPDeviceID, Model FROM Win32_DiskDrive WHERE InterfaceType = 'USB'"
        )
        for item in drives:
            _add(found, getattr(item, "PNPDeviceID", None),
                 getattr(item, "Model", None), "EXTERNAL_DRIVE", True)

        disk_devices = services.ExecQuery(
            "SELECT PNPDeviceID, Name FROM Win32_PnPEntity WHERE PNPClass = 'DiskDrive'"
        )
        for item in disk_devices:
            pnp_id = getattr(item, "PNPDeviceID", None)
            if isinstance(pnp_id, str) and "USBSTOR\\" in pnp_id.upper():
                _add(found, pnp_id, getattr(item, "Name", None), "EXTERNAL_DRIVE", True)

        devices = services.ExecQuery(
            "SELECT PNPDeviceID, Name, PNPClass FROM Win32_PnPEntity"
        )
        category_map = {
            "usb": "USB_PERIPHERAL", "hidclass": "INPUT_DEVICE",
            "keyboard": "INPUT_DEVICE", "mouse": "INPUT_DEVICE",
            "bluetooth": "BLUETOOTH", "image": "CAMERA_OR_SCANNER",
            "printer": "PRINTER", "modem": "MODEM",
        }
        for item in devices:
            pnp_id = getattr(item, "PNPDeviceID", None)
            pnp_class = str(getattr(item, "PNPClass", "") or "").casefold()
            normalized_id = str(pnp_id or "").upper()
            if not any(marker in normalized_id for marker in
                       ("USB\\VID_", "USBSTOR\\", "HID\\VID_", "BTHENUM\\", "BTHLEDEVICE\\")):
                continue
            if "USBSTOR\\" in normalized_id or pnp_class == "diskdrive":
                is_external_disk = ("USBSTOR\\" in normalized_id
                                    or (pnp_class == "diskdrive" and normalized_id.startswith("USB\\VID_")))
                category = "EXTERNAL_DRIVE" if is_external_disk else None
            else:
                category = category_map.get(pnp_class)
                if category is None and normalized_id.startswith("USB\\VID_"):
                    category = "USB_PERIPHERAL"
            if category:
                _add(found, pnp_id, getattr(item, "Name", None), category,
                     category == "EXTERNAL_DRIVE")
        return sorted(found.values(), key=lambda item: (not item["is_storage"], item["device_key"]))[:128]
    except Exception as exc:
        logging.getLogger("labguard_client").warning(
            "Peripheral inventory collection failed (%s)", type(exc).__name__
        )
        return None
    finally:
        pythoncom.CoUninitialize()


def _add(found: dict[str, dict], pnp_id, name, category: str, is_storage: bool) -> None:
    if not isinstance(pnp_id, str) or not pnp_id.strip():
        return
    value = str(name or "").strip()
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    value = " ".join(value.split())[:256] or category.replace("_", " ").title()
    key = hashlib.sha256(pnp_id.casefold().encode("utf-8", "replace")).hexdigest()
    found[key] = {"device_key": key, "name": value, "category": category,
                  "is_storage": is_storage}
