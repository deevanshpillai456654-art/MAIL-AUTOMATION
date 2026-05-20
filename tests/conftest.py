import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "INTEMO_PROVIDER_CREDENTIALS_PATH",
        str(tmp_path / "provider_credentials.json"),
    )
