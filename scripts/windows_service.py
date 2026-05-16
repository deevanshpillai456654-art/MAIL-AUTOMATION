"""
Auto-start configuration for INTEMO
"""

import os
import sys
import winreg
import shutil
from pathlib import Path


def get_install_path() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).parent.parent)


def get_exe_path() -> str:
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.join(get_install_path(), "backend", "main.py")


def add_to_startup():
    """Add to Windows startup (current user)"""
    exe_path = get_exe_path()

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)

    try:
        winreg.SetValueEx(key, "AIEmailOrganizer", 0, winreg.REG_SZ, f'"{exe_path}" --startup')
        winreg.CloseKey(key)
        print("Added to Windows startup (current user)")
        return True
    except Exception as e:
        print(f"Failed to add to startup: {e}")
        return False


def remove_from_startup():
    """Remove from Windows startup"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)

    try:
        winreg.DeleteValue(key, "AIEmailOrganizer")
        winreg.CloseKey(key)
        print("Removed from Windows startup")
        return True
    except FileNotFoundError:
        print("Not in startup")
        return True
    except Exception as e:
        print(f"Failed to remove from startup: {e}")
        return False


def is_in_startup() -> bool:
    """Check if app is in startup"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)

    try:
        value, _ = winreg.QueryValueEx(key, "AIEmailOrganizer")
        winreg.CloseKey(key)
        return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def create_startup_shortcut():
    """Create Desktop shortcut"""
    try:
        import win32com.client
        import pythoncom

        pythoncom.CoInitialize()

        desktop = os.path.join(os.path.expanduser("Desktop"), "INTEMO.lnk")
        exe_path = get_exe_path()

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(desktop)
        shortcut.TargetPath = exe_path
        shortcut.WorkingDirectory = os.path.dirname(exe_path)
        shortcut.Description = "INTEMO"
        shortcut.Save()

        print(f"Created shortcut: {desktop}")
        return True

    except ImportError:
        print("pywin32 not installed. Install with: pip install pywin32")
        return False
    except Exception as e:
        print(f"Failed to create shortcut: {e}")
        return False


def register_service():
    """Register as Windows service (requires admin)"""
    exe_path = get_exe_path()

    try:
        import win32serviceutil
        import win32service
        import servicemanager

        win32serviceutil.InstallService(
            pythoncom.GetCurrentThread(),
            "AIEmailOrganizer",
            "INTEMO",
            exe_path,
            args="--service"
        )
        print("Registered as Windows service")
        return True

    except ImportError:
        print("pywin32 not installed for service registration")
        return False
    except Exception as e:
        print(f"Service registration requires admin: {e}")
        return False


def main():
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "--add-startup":
            add_to_startup()

        elif command == "--remove-startup":
            remove_from_startup()

        elif command == "--check-startup":
            if is_in_startup():
                print("In startup")
            else:
                print("Not in startup")

        elif command == "--shortcut":
            create_startup_shortcut()

        elif command == "--register-service":
            register_service()

    else:
        print("INTEMO - Auto-start Configuration")
        print("=" * 40)
        print(f"Installation path: {get_install_path()}")
        print(f"Executable: {get_exe_path()}")
        print(f"In startup: {is_in_startup()}")
        print()
        print("Commands:")
        print("  --add-startup      Add to Windows startup")
        print("  --remove-startup    Remove from startup")
        print("  --check-startup     Check startup status")
        print("  --shortcut         Create desktop shortcut")
        print("  --register-service Register as Windows service")


if __name__ == "__main__":
    main()
