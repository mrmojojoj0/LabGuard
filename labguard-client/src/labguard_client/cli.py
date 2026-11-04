import argparse
import asyncio
import os
from pathlib import Path
from getpass import getpass

from labguard_client.agent import AgentClient
from labguard_client.identity import DeviceIdentity


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
    run.add_argument("--insecure-dev", action="store_true", help="Allow plaintext HTTP for local development only")
    enroll.add_argument("--insecure-dev", action="store_true", help="Allow plaintext HTTP for local development only")
    args = parser.parse_args()
    identity = DeviceIdentity.load_or_create(Path(args.state_dir))
    client = AgentClient(args.server, identity, allow_insecure_dev=args.insecure_dev)
    if args.command == "enroll":
        result = client.enroll(args.code or getpass("One-time enrollment code: "))
        print(f"Enrollment submitted: device_id={result['id']} state={result['enrollment_state']}")
    else:
        try:
            asyncio.run(client.run_forever())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
