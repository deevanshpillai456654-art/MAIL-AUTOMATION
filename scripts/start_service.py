import subprocess
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent

    print("Installing dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=project_root,
        check=True,
    )

    print("Starting INTEMO Service...")
    print("API will be available at: http://127.0.0.1:4597")
    print("API docs at: http://127.0.0.1:4597/docs")

    subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "4597"],
        cwd=project_root,
    )

if __name__ == "__main__":
    main()
