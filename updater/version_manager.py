import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

APP_VERSION = "14.0.1B"


class Version:
    def __init__(self, major: int, minor: int, patch: int, prerelease: str = "", build: str = ""):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.prerelease = prerelease
        self.build = build

    def __str__(self):
        v = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            v += f"-{self.prerelease}"
        if self.build:
            v += f"+{self.build}"
        return v

    def __repr__(self):
        return f"Version({self.major}, {self.minor}, {self.patch}, '{self.prerelease}', '{self.build}')"

    def __eq__(self, other):
        return self._compare(other) == 0

    def __lt__(self, other):
        return self._compare(other) < 0

    def __le__(self, other):
        return self.__eq__(other) or self.__lt__(other)

    def __gt__(self, other):
        return self._compare(other) > 0

    def __ge__(self, other):
        return self.__eq__(other) or self.__gt__(other)

    def _compare(self, other) -> int:
        if self.major != other.major:
            return self.major - other.major
        if self.minor != other.minor:
            return self.minor - other.minor
        if self.patch != other.patch:
            return self.patch - other.patch

        if self.prerelease and other.prerelease:
            return self._compare_prerelease(other.prerelease)
        elif self.prerelease and not other.prerelease:
            return -1
        elif not self.prerelease and other.prerelease:
            return 1

        return 0

    def _compare_prerelease(self, other: str) -> int:
        self_parts = self.prerelease.split('.')
        other_parts = other.split('.')
        for i in range(max(len(self_parts), len(other_parts))):
            s = self_parts[i] if i < len(self_parts) else ""
            o = other_parts[i] if i < len(other_parts) else ""

            s_is_num = s.isdigit()
            o_is_num = o.isdigit()

            if s_is_num and o_is_num:
                diff = int(s) - int(o)
                if diff != 0:
                    return diff
            elif s_is_num:
                return -1
            elif o_is_num:
                return 1
            else:
                if s != o:
                    return -1 if s < o else 1

        return 0

    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def is_compatible(self, other, mode: str = "major") -> bool:
        if mode == "major":
            return self.major == other.major
        elif mode == "minor":
            return self.major == other.major and self.minor == other.minor
        elif mode == "patch":
            return self.major == other.major and self.minor == other.minor and self.patch == other.patch
        return False

    @staticmethod
    def parse(version_string: str) -> "Version":
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+([a-zA-Z0-9.]+))?$', version_string)
        if not match:
            raise ValueError(f"Invalid version string: {version_string}")

        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        prerelease = match.group(4) or ""
        build = match.group(5) or ""

        return Version(major, minor, patch, prerelease, build)


class VersionManager:
    def __init__(self, app_name="AIEmailOrganizer"):
        self.app_name = app_name
        self.install_path = self._get_install_path()
        self.runtime_home = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or self.install_path,
            self.app_name,
        )
        self.version_file = os.path.join(self.runtime_home, "version.json")
        self.history_file = os.path.join(self.runtime_home, "data", "version_history.json")
        self.compatibility_file = os.path.join(self.runtime_home, "configs", "compatibility.json")
        self.log_file = os.path.join(self.runtime_home, "logs", "version_manager.log")

    def _get_install_path(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"Software\\{self.app_name}", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return value
        except Exception:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        print(log_entry)
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, "a") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass

    def get_current_version(self) -> Version:
        if os.path.exists(self.version_file):
            try:
                with open(self.version_file, "r") as f:
                    data = json.load(f)
                    return Version.parse(data.get("version", "14.0.1B"))
            except Exception as e:
                self.log(f"Failed to read version: {e}", "WARNING")

        return Version(9, 7, 0)

    def set_current_version(self, version: Version, reason: str = ""):
        version_data = {
            "version": str(version),
            "updated_at": datetime.now().isoformat(),
            "reason": reason
        }
        os.makedirs(os.path.dirname(self.version_file), exist_ok=True)
        with open(self.version_file, "w") as f:
            json.dump(version_data, f, indent=2)

        self._add_to_history(version, reason)

    def _add_to_history(self, version: Version, reason: str):
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    history = json.load(f)
            except Exception:
                pass

        history.insert(0, {
            "version": str(version),
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })

        history = history[:50]

        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, "w") as f:
            json.dump(history, f, indent=2)

    def get_version_history(self) -> List[Dict]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def resolve_target_version(self, target: str) -> Tuple[Version, bool]:
        self.log(f"Resolving target version: {target}")
        current = self.get_current_version()

        if target == "latest":
            return self._get_latest_available(), True
        elif target == "next":
            return Version(current.major, current.minor + 1, 0), True
        elif target.startswith("+"):
            increment = target[1:]
            if increment == "major":
                return Version(current.major + 1, 0, 0), True
            elif increment == "minor":
                return Version(current.major, current.minor + 1, 0), True
            elif increment == "patch":
                return Version(current.major, current.minor, current.patch + 1), True

        try:
            target_version = Version.parse(target)
            return target_version, True
        except ValueError:
            self.log(f"Invalid version string: {target}", "ERROR")
            return current, False

    def _get_latest_available(self) -> Version:
        try:
            manifest_path = os.path.join(self.install_path, "updates", "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                    return Version.parse(data.get("version", "14.0.1B"))
        except Exception:
            pass

        return self.get_current_version()

    def check_compatibility(self, target_version: Version) -> Tuple[bool, str]:
        self.log(f"Checking compatibility for {target_version}")

        current = self.get_current_version()

        compat_file = self.compatibility_file
        if os.path.exists(compat_file):
            try:
                with open(compat_file, "r") as f:
                    compat_data = json.load(f)

                min_version = compat_data.get("minimum_version")
                if min_version:
                    min_v = Version.parse(min_version)
                    if target_version < min_v:
                        return False, f"Target version below minimum: {min_version}"

                max_version = compat_data.get("maximum_version")
                if max_version:
                    max_v = Version.parse(max_version)
                    if target_version > max_v:
                        return False, f"Target version exceeds maximum: {max_version}"

                breaking_changes = compat_data.get("breaking_changes", {})
                for version_str, changes in breaking_changes.items():
                    check_v = Version.parse(version_str)
                    if check_v.major > current.major:
                        return False, f"Breaking change detected in {version_str}: {changes}"

            except Exception as e:
                self.log(f"Failed to check compatibility: {e}", "WARNING")

        if target_version.major > current.major:
            return False, "Major version upgrade not supported"
        elif target_version.major == current.major and target_version.minor > current.minor:
            return True, "Minor version upgrade OK"
        elif target_version.major == current.major and target_version.minor == current.minor:
            if target_version.patch > current.patch:
                return True, "Patch update OK"
            elif target_version.patch < current.patch:
                return False, "Downgrade not allowed without explicit consent"
        elif target_version < current:
            return False, "Version downgrade not allowed without explicit consent"

        return True, "Compatible"

    def prevent_downgrade(self, target_version: Version) -> bool:
        current = self.get_current_version()
        if target_version < current:
            self.log("Downgrade prevented", "WARNING")
            return False
        return True

    def can_downgrade(self, target_version: Version, explicit_consent: bool = False) -> bool:
        current = self.get_current_version()
        if target_version >= current:
            return True

        if explicit_consent:
            return True

        return False

    def get_next_compatible_version(self) -> Optional[Version]:
        current = self.get_current_version()
        versions = [
            Version(current.major, current.minor, current.patch + 1),
            Version(current.major, current.minor + 1, 0),
            Version(current.major + 1, 0, 0),
        ]

        for v in versions:
            compatible, _ = self.check_compatibility(v)
            if compatible:
                return v

        return None

    def validate_version_format(self, version_string: str) -> bool:
        try:
            Version.parse(version_string)
            return True
        except ValueError:
            return False


def main():
    vm = VersionManager()

    current = vm.get_current_version()
    print(f"Current version: {current}")

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "set":
            if len(sys.argv) > 2:
                v = Version.parse(sys.argv[2])
                reason = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "Manual update"
                vm.set_current_version(v, reason)
                print(f"Version set to: {v}")
            else:
                print("Usage: version_manager.py set <version> [reason]")
        elif command == "history":
            for h in vm.get_version_history():
                print(f"{h['version']} - {h['timestamp']} - {h.get('reason', '')}")
        elif command == "check":
            if len(sys.argv) > 2:
                target = Version.parse(sys.argv[2])
                compatible, reason = vm.check_compatibility(target)
                print(f"Compatible: {compatible}")
                print(f"Reason: {reason}")
            else:
                print("Usage: version_manager.py check <version>")
        elif command == "next":
            next_v = vm.get_next_compatible_version()
            if next_v:
                print(f"Next compatible version: {next_v}")
            else:
                print("No compatible version available")


if __name__ == "__main__":
    main()