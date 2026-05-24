"""
Extended System Tray for AI Email Organizer
Provides full menu, status indicators, and quick controls
"""

import os
import sys
import threading
import time

import requests


class SystemTray:
    def __init__(self, port: int = 4597):
        self.port = port
        self.api_base = f"http://127.0.0.1:{port}"
        self.running = False
        self.tray = None

    def create_tray(self):
        try:
            from PIL import Image, ImageDraw
            from pystray import Icon, Menu, MenuItem
        except ImportError:
            print("pystray not available. Run: pip install pystray")
            return None

        width = 64
        height = 64
        image = Image.new("RGB", (width, height), color=(102, 126, 234))
        draw = ImageDraw.Draw(image)
        draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255))
        draw.text((20, 26), "AI", fill=(102, 126, 234))

        menu = Menu(
            MenuItem("Open Dashboard", self.open_dashboard),
            MenuItem("Pause Processing", self.toggle_processing),
            Menu.SEPARATOR,
            MenuItem("Status", self.show_status, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Restart Service", self.restart_service),
            MenuItem("Settings", self.open_settings),
            Menu.SEPARATOR,
            MenuItem("Exit", self.exit_app)
        )

        icon = Icon("AI Email Organizer", image, "AI Email Organizer", menu)
        return icon

    def open_dashboard(self):
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.port}/dashboard")
        except Exception:
            pass

    def toggle_processing(self):
        print("Toggle processing...")

    def show_status(self):
        try:
            res = requests.get(f"{self.api_base}/api/v1/health", timeout=2)
            if res.ok:
                data = res.json()
                return f"Status: {data.get('status', 'unknown')}"
        except Exception:
            pass
        return "Status: Offline"

    def restart_service(self):
        print("Restarting service...")

    def open_settings(self):
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.port}/dashboard?page=settings")
        except Exception:
            pass

    def exit_app(self):
        self.running = False
        sys.exit(0)

    def run(self):
        self.tray = self.create_tray()
        if self.tray:
            self.running = True
            self.tray.run()
        else:
            print("System tray not available")


class TrayStatusMonitor:
    def __init__(self, port: int = 4597):
        self.port = port
        self.status = "offline"
        self.emails_processed = 0
        self.cpu_usage = 0
        self.ram_usage = 0
        self.monitor_thread = None

    def check_status(self) -> dict:
        try:
            res = requests.get(f"http://127.0.0.1:{self.port}/api/v1/health/detailed", timeout=2)
            if res.ok:
                data = res.json()
                self.status = data.get("status", "unknown")

                if data.get("system"):
                    self.cpu_usage = data["system"].get("cpu", {}).get("usage_percent", 0)
                    self.ram_usage = data["system"].get("memory", {}).get("used_gb", 0)

                if data.get("metrics"):
                    self.emails_processed = data["metrics"].get("total_classifications", 0)

                return {
                    "status": self.status,
                    "cpu": self.cpu_usage,
                    "ram": self.ram_usage,
                    "emails": self.emails_processed
                }
        except Exception:
            self.status = "offline"

        return {
            "status": self.status,
            "cpu": 0,
            "ram": 0,
            "emails": 0
        }

    def start_monitoring(self):
        def monitor():
            while True:
                status = self.check_status()
                time.sleep(5)

        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()

    def get_status_text(self) -> str:
        status = self.check_status()
        return f"""
Status: {status['status'].title()}
CPU: {status['cpu']:.1f}%
RAM: {status['ram']:.1f}GB
Emails: {status['emails']}
"""


def create_tray_menu():
    """Create dynamic menu with current status"""
    try:
        from pystray import Menu, MenuItem
    except ImportError:
        return None

    monitor = TrayStatusMonitor()
    status = monitor.check_status()

    status_text = f"Status: {status['status'].title()} | CPU: {status['cpu']:.0f}%"

    menu = Menu(
        MenuItem(status_text, enabled=False),
        Menu.SEPARATOR,
        MenuItem(f"Emails: {status['emails']}", enabled=False),
        MenuItem(f"RAM: {status['ram']:.1f}GB", enabled=False),
        Menu.SEPARATOR,
        MenuItem("Open Dashboard", lambda i: open_dashboard()),
        MenuItem("Pause Processing", lambda i: toggle_processing()),
        Menu.SEPARATOR,
        MenuItem("Restart", lambda i: restart_service()),
        MenuItem("Exit", lambda i: exit_app())
    )

    return menu


def open_dashboard():
    import webbrowser
    port = os.environ.get("API_PORT", "4597")
    webbrowser.open(f"http://127.0.0.1:{port}/dashboard")


def toggle_processing():
    print("Processing toggled")


def restart_service():
    print("Service restart requested")


def exit_app():
    sys.exit(0)


def start_tray(port: int = 4597):
    tray = SystemTray(port)
    tray.run()


if __name__ == "__main__":
    start_tray()
