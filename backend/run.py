#!/usr/bin/env python3
"""
Service runner for AI Email Organizer
Provides easy startup and status checks
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICE_DIR = PROJECT_ROOT
_API_PORT = int(os.environ.get("API_PORT", "4597"))
API_URL = f"http://127.0.0.1:{_API_PORT}"


def check_python_version():
    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8+ required")
        print(f"Current version: {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True


def check_dependencies():
    print("Checking dependencies...")
    missing = []

    required = ["fastapi", "uvicorn", "pydantic", "numpy", "sklearn"]
    for package in required:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        return False

    print("All dependencies installed.")
    return True


def wait_for_service(timeout=30):
    print(f"Waiting for service (timeout: {timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            response = requests.get(f"{API_URL}/api/v1/health", timeout=2)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)

    return False


def start_service():
    print("\nStarting AI Email Organizer Service...")
    print("-" * 40)

    process = subprocess.Popen(
        [sys.executable, "-m", "backend.main"],
        cwd=str(SERVICE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    return process


def _load_psutil():
    import psutil
    return psutil


def _addr_port(addr):
    if not addr:
        return None
    if hasattr(addr, "port"):
        return addr.port
    if isinstance(addr, tuple) and len(addr) >= 2:
        return addr[1]
    return None


def _find_service_pids(psutil_module):
    pids = set()
    current_pid = os.getpid()
    listen_status = getattr(psutil_module, "CONN_LISTEN", "LISTEN")

    for connection in psutil_module.net_connections(kind="inet"):
        if getattr(connection, "status", None) != listen_status:
            continue
        if _addr_port(getattr(connection, "laddr", None)) != _API_PORT:
            continue

        pid = getattr(connection, "pid", None)
        if pid and pid != current_pid:
            pids.add(pid)

    return sorted(pids)


def stop_service(timeout=5):
    psutil_module = _load_psutil()
    pids = _find_service_pids(psutil_module)

    if not pids:
        print("Service not running")
        return False

    stopped = False
    for pid in pids:
        try:
            process = psutil_module.Process(pid)
            print(f"Stopping service process {pid}...")
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except psutil_module.TimeoutExpired:
                print(f"Service process {pid} did not stop in time; forcing shutdown...")
                process.kill()
                process.wait(timeout=timeout)
            stopped = True
        except (psutil_module.NoSuchProcess, psutil_module.AccessDenied) as exc:
            print(f"Could not stop process {pid}: {exc}")

    if stopped:
        print("Service stopped")
    return stopped


def status_check():
    try:
        response = requests.get(f"{API_URL}/api/v1/health", timeout=5)
        if response.ok:
            data = response.json()
            print(f"Status: {data.get('status')}")
            print(f"Version: {data.get('version')}")
            return True
    except requests.RequestException:
        pass

    print("Service not running")
    return False


def main():
    print("=" * 50)
    print("AI Email Organizer - Service Runner")
    print("=" * 50)

    if not check_python_version():
        sys.exit(1)

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "start":
            if not check_dependencies():
                sys.exit(1)

            process = start_service()

            if wait_for_service():
                print("\nService started successfully!")
                print(f"API: {API_URL}")
                print(f"Docs: {API_URL}/docs")
                print("\nPress Ctrl+C to stop")

                try:
                    process.wait()
                except KeyboardInterrupt:
                    print("\nStopping service...")
                    process.terminate()
                    process.wait()
            else:
                print("Service failed to start")
                process.terminate()
                sys.exit(1)

        elif command == "status":
            if status_check():
                sys.exit(0)
            else:
                sys.exit(1)

        elif command == "stop":
            stop_service()
            sys.exit(0)

        else:
            print(f"Unknown command: {command}")
            print("Usage: python run.py [start|status|stop]")

    else:
        print("\nUsage: python run.py [start|status|stop]")
        print("\nQuick start:")
        print("  python run.py start  - Start the service")
        print("  python run.py status - Check service status")
        print("  python run.py stop   - Stop the service")


if __name__ == "__main__":
    main()
