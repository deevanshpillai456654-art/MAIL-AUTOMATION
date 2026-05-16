"""Offline model inventory helper for INTEMO v14.0.1B.

The lightweight build does not download models automatically. Place signed
ONNX models in local-service/models or the configured AIO_MODEL_DIR, then run
this script with --check to validate that the directory is usable.
"""

from pathlib import Path
import sys


def get_models_dir():
    project_root = Path(__file__).parent.parent
    return project_root / "backend" / "models"


def check_models():
    models_dir = get_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_files = sorted(models_dir.rglob("*.onnx"))
    if not onnx_files:
        print("No ONNX models found. The app will use the offline deterministic fallback.")
        return True
    print("ONNX models available:")
    for path in onnx_files:
        print(f"- {path.relative_to(models_dir)}")
    return True


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in {"--check", "check"}:
        print("Automatic model downloads are disabled in the lightweight local-first build.")
        print("Place ONNX models in local-service/models and run: python scripts/download_models.py --check")
        return
    check_models()


if __name__ == "__main__":
    main()

