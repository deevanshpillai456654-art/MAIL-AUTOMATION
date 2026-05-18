from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class TallyEndpoint:
    host: str = "localhost"
    port: int = 9000
    use_tls: bool = False

    @property
    def url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.host}:{self.port}"


class TallyXmlClient:
    def __init__(self, endpoint: TallyEndpoint, timeout: float = 8.0, retries: int = 2):
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = max(1, retries)

    def post_xml(self, xml: str) -> str:
        last_error: Exception | None = None
        payload = xml.encode("utf-8")
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(
                    self.endpoint.url,
                    data=payload,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - user configured Tally endpoint
                    return response.read().decode("utf-8", errors="replace")
            except Exception as exc:
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(0.15 * (attempt + 1))
        raise ConnectionError(f"Tally XML request failed: {last_error}")
