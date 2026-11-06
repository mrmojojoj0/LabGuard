import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from getpass import getpass
import sys

from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity
from labguard_client.instance import InstanceAlreadyRunning


def main():
    parser = argparse.ArgumentParser(prog="labguard-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    enroll = sub.add_parser("enroll", help="Submit a pending enrollment request")
    enroll.add_argument("--server", required=True)
    enroll.add_argument("--code")
    enroll.add_argument("--state-dir", default=os.getenv("PROGRAMDATA", str(Path.home())) + "/LabGuard")
    run = sub.add_parser("run", help="Connect and send authenticated heartbeats")
    run.add_argument("--server", required=True)
    run.add_argument("--state-dir", default=os.getenv("PROGRAMDATA", str(Path.home())) + "/LabGuard")
    run.add_argument("--telemetry-interval-seconds", type=float,
                     default=float(os.getenv("LABGUARD_TELEMETRY_INTERVAL_SECONDS", "30")))
    run.add_argument("--software-inventory-interval-seconds", type=float,
                     default=float(os.getenv("LABGUARD_SOFTWARE_INVENTORY_INTERVAL_SECONDS", "21600")))
    run.add_argument("--insecure-dev", action="store_true", help="Allow plaintext HTTP for local development only")
    enroll.add_argument("--insecure-dev", action="store_true", help="Allow plaintext HTTP for local development only")
    service = sub.add_parser("service", help="Prepare or manage the Windows Service")
    service.add_argument("action", choices=("prepare", "install", "uninstall", "start", "stop", "restart", "status"))
    service.add_argument("--server")
    service.add_argument("--state-dir", default=os.getenv("PROGRAMDATA", str(Path.home())) + "/LabGuard")
    service.add_argument("--telemetry-interval-seconds", type=float,
                          default=float(os.getenv("LABGUARD_TELEMETRY_INTERVAL_SECONDS", "30")))
    service.add_argument("--software-inventory-interval-seconds", type=float,
                          default=float(os.getenv("LABGUARD_SOFTWARE_INVENTORY_INTERVAL_SECONDS", "21600")))
    service.add_argument("--insecure-dev", action="store_true",
                         help="Allow plaintext HTTP for local development only (prepare/install required)")
    args = parser.parse_args()
    state_dir = Path(args.state_dir)
    if args.command == "service":
        if args.insecure_dev and args.action not in {"prepare", "install"}:
            parser.error("service --insecure-dev is valid only with prepare or install")
        state_dir.mkdir(parents=True, exist_ok=True)
        _configure_logging(state_dir)
        if args.action == "prepare":
            if not args.server:
                parser.error("service prepare requires --server https://... (or --insecure-dev for local development)")
            from labguard_client.windows_service import prepare_service
            print(f"Prepared service configuration: {prepare_service(args.server, state_dir, args.telemetry_interval_seconds,
                                                                       args.software_inventory_interval_seconds,
                                                                       allow_insecure_dev=args.insecure_dev)}")
        else:
            from labguard_client.windows_service import service_command
            print(service_command(args.action, insecure_dev=args.insecure_dev))
        return

    state_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(state_dir)
    if args.command == "run":
        identity = DeviceIdentity.load_existing(state_dir)
    else:
        identity = DeviceIdentity.load_or_create(state_dir)
    client = AgentClient(args.server, identity, allow_insecure_dev=args.insecure_dev,
                         telemetry_interval_seconds=args.telemetry_interval_seconds if args.command == "run" else 30,
                         software_inventory_interval_seconds=args.software_inventory_interval_seconds if args.command == "run" else 6 * 60 * 60)
    if args.command == "enroll":
        result = client.enroll(args.code or getpass("One-time enrollment code: "))
        print(f"Enrollment submitted: device_id={result['id']} state={result['enrollment_state']}")
    else:
        try:
            asyncio.run(client.run_forever())
        except KeyboardInterrupt:
            pass
        except InstanceAlreadyRunning as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc


def _configure_logging(state_dir: Path) -> None:
    logger = logging.getLogger("labguard_client")
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(state_dir / "labguard-agent.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


if __name__ == "__main__":
    main()
