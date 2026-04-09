"""niimbotd — persistent BLE daemon for NIIMBOT printer."""
import argparse
import json
import os
import signal
import sys


def cli():
    parser = argparse.ArgumentParser(prog="niimbotd", description="NIIMBOT BLE printer daemon")
    parser.add_argument("command", choices=["start", "stop", "status", "run"],
                        help="start=background, stop=kill, status=show state, run=foreground")
    args = parser.parse_args()

    if args.command == "run":
        from niimbot.daemon.server import main
        main()

    elif args.command == "start":
        import subprocess
        from niimbot.labels import get_data_dir

        # Check if already running
        pid_path = get_data_dir() / ".niimbotd.pid"
        if pid_path.exists():
            pid = int(pid_path.read_text().strip())
            try:
                os.kill(pid, 0)  # check if process exists
                print(f"niimbotd already running (pid {pid})")
                return
            except ProcessLookupError:
                pass  # stale PID file

        proc = subprocess.Popen(
            [sys.executable, "-m", "niimbot.daemon.server"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"niimbotd started (pid {proc.pid})")

    elif args.command == "stop":
        from niimbot.labels import get_data_dir
        pid_path = get_data_dir() / ".niimbotd.pid"
        if not pid_path.exists():
            print("niimbotd not running (no PID file)")
            return
        pid = int(pid_path.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"niimbotd stopped (pid {pid})")
        except ProcessLookupError:
            print(f"niimbotd not running (stale PID {pid})")
            pid_path.unlink()

    elif args.command == "status":
        import asyncio
        from niimbot.daemon.client import DaemonClient

        async def _status():
            client = DaemonClient()
            try:
                result = await client.status()
                print(f"State:     {result.get('state', '?')}")
                print(f"Transport: {result.get('transport', '?') or '-'}")
                print(f"Printer:   {result.get('printer_name', '?')}")
                print(f"Battery:   {result.get('power_level', '?')}%")
                print(f"Paper:     {result.get('paper_state', '?')}")
                print(f"Uptime:    {result.get('uptime_s', '?')}s")
            except Exception:
                print("niimbotd not running or not responding")

        asyncio.run(_status())
