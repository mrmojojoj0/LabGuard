"""Narrow Session 0 broker target for approved per-user WinGet uninstalls."""
from __future__ import annotations

import base64
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

from labguard_client.software_management import (
    PackageManagerUnavailable,
    SoftwareJobOffer,
    UnsupportedExecutionContext,
    execute_package_job,
    sanitize_output,
)
from labguard_client.software_inventory import collect_software_inventory


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    try:
        encoded, output_path = args
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        offer = SoftwareJobOffer.parse(payload)
        # The service broker may only invoke a user-context uninstall. The helper
        # cannot be used to install packages or perform machine-scope operations.
        if offer.action != "UNINSTALL" or offer.package_manager != "WINGET" or offer.installation_scope != "USER":
            raise UnsupportedExecutionContext("unsupported_active_user_operation")
        if datetime.fromisoformat(offer.expires_at.replace("Z", "+00:00")) <= datetime.now(UTC):
            raise UnsupportedExecutionContext("software_job_expired")
        inventory = collect_software_inventory()
        if not inventory.complete or not any(
            (item.get("package_id") or "").casefold() == offer.package_id.casefold()
            and item.get("source") == "WINGET"
            and item.get("installation_scope") == "USER"
            and "WINDOWS_REGISTRY" in item.get("discovery_sources", [])
            for item in inventory.entries
        ):
            raise UnsupportedExecutionContext("package_not_verified_for_active_user")
        result = execute_package_job(offer, local_system=False, administrator=False,
                                     service_context=False)
        returncode = result.returncode
        output = result.output
        if returncode == 0 and not result.timed_out and not result.cancelled:
            refreshed = collect_software_inventory()
            still_present = any(
                (item.get("package_id") or "").casefold() == offer.package_id.casefold()
                and item.get("source") == "WINGET"
                and item.get("installation_scope") == "USER"
                and "WINDOWS_REGISTRY" in item.get("discovery_sources", [])
                for item in refreshed.entries
            )
            if not refreshed.complete or still_present:
                returncode = 1
                output = (output + " | " if output else "") + "user_scope_inventory_verification_failed"
        response = {"returncode": returncode, "output": output,
                    "timed_out": result.timed_out, "cancelled": result.cancelled}
    except (ValueError, TypeError, KeyError, PackageManagerUnavailable,
            UnsupportedExecutionContext, OSError) as exc:
        response = {"returncode": 1, "output": str(exc)[:1000],
                    "timed_out": False, "cancelled": False}
    except Exception as exc:
        # Always return a bounded diagnostic to the service instead of leaving
        # only a generic child-process exit code in the job record.
        response = {"returncode": 1, "output": sanitize_output(
                        f"helper_error_{type(exc).__name__}: {exc}"),
                    "timed_out": False, "cancelled": False}
    try:
        # Exclusive creation prevents following or overwriting an existing path.
        with Path(output_path).open("x", encoding="utf-8") as output:
            json.dump(response, output, separators=(",", ":"))
        return 0
    except OSError:
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
