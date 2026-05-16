import pytest


@pytest.fixture(autouse=True)
def isolated_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "INTEMO_PROVIDER_CREDENTIALS_PATH",
        str(tmp_path / "provider_credentials.json"),
    )
