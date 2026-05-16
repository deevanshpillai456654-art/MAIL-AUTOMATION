from __future__ import annotations
import shutil
import sys
from pathlib import Path


def install(source_platform: Path, target_project: Path) -> None:
    if source_platform.name != "platform":
        raise ValueError("source_platform must be the /platform folder")
    target = target_project / "platform"
    if target.exists():
        backup = target_project / "platform.backup"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(target), str(backup))
    shutil.copytree(source_platform, target)
    print(f"Installed platform-only layer to {target}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python platform/tools/install_platform_only.py <source_platform_folder> <target_project_folder>")
    install(Path(sys.argv[1]), Path(sys.argv[2]))
