import os
import subprocess
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent
    api_port = os.environ.get("API_PORT", "4597")

    print("Installing dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=project_root,
        check=True,
    )

    print("Starting INTEMO Service...")
    print(f"API will be available at: http://127.0.0.1:{api_port}")
    print(f"API docs at: http://127.0.0.1:{api_port}/docs")

    subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", api_port],
        cwd=project_root,
    )

if __name__ == "__main__":
    main()
