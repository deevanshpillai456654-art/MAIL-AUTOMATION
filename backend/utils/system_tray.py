"""
System tray support for AI Email Organizer
Provides background service with system tray icon
"""

import sys
import time
from pathlib import Path


class SystemTray:
    def __init__(self, app_name: str = "AI Email Organizer", port: int = 4597):
        self.app_name = app_name
        self.port = port
        self.running = False

    def create_tray_icon(self):
        try:
            from PIL import Image, ImageDraw
            from pystray import Icon, Menu, MenuItem
        except ImportError:
            print("pystray not available. Install: pip install pystray")
            return None

        width = 64
        height = 64
        image = Image.new("RGB", (width, height), color=(102, 126, 234))
        draw = ImageDraw.Draw(image)
        draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255))
        draw.text((24, 28), "AI", fill=(102, 126, 234))

        menu = Menu(
            MenuItem("Open Dashboard", self.open_dashboard),
            MenuItem("Check Status", self.check_status),
            MenuItem("Settings", self.open_settings),
            MenuItem("Separator"),
            MenuItem("Start on Boot", self.toggle_autostart),
            MenuItem("Separator"),
            MenuItem("Exit", self.exit_app)
        )

        icon = Icon(self.app_name, image, self.app_name, menu)
        return icon

    def open_dashboard(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{self.port}")

    def check_status(self):
        import requests
        try:
            response = requests.get(f"http://localhost:{self.port}/api/v1/health", timeout=2)
            if response.ok:
                print("Service is running")
        except Exception:
            print("Service is not running")

    def open_settings(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{self.port}/docs")

    def toggle_autostart(self):
        print("Autostart toggled")

    def exit_app(self):
        self.running = False
        sys.exit(0)

    def run(self):
        icon = self.create_tray_icon()
        if icon:
            self.running = True
            icon.run()


class ServiceManager:
    def __init__(self, port: int = 4597):
        self.port = port
        self.process = None

    def start_service(self):
        import subprocess
        import sys

        service_path = Path(__file__).parent.parent / "main.py"
        self.process = subprocess.Popen(
            [sys.executable, str(service_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        print(f"Service started (PID: {self.process.pid})")

    def stop_service(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
            print("Service stopped")

    def restart_service(self):
        self.stop_service()
        time.sleep(2)
        self.start_service()

    def check_status(self) -> bool:
        import requests
        try:
            response = requests.get(f"http://localhost:{self.port}/api/v1/health", timeout=2)
            return response.ok
        except Exception:
            return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI Email Organizer Service Manager")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "tray"])
    parser.add_argument("--port", type=int, default=4597, help="Service port")

    args = parser.parse_args()
    manager = ServiceManager(args.port)

    if args.command == "start":
        manager.start_service()

    elif args.command == "stop":
        manager.stop_service()

    elif args.command == "restart":
        manager.restart_service()

    elif args.command == "status":
        if manager.check_status():
            print("Service is running")
        else:
            print("Service is not running")

    elif args.command == "tray":
        tray = SystemTray(port=args.port)
        tray.run()


if __name__ == "__main__":
    main()
