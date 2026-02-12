from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from urllib import request
from urllib.error import HTTPError, URLError


LOGGER = logging.getLogger(__name__)


class DiscordNotifyError(RuntimeError):
    """Raised when Discord message sending fails."""


@dataclass(frozen=True)
class DiscordNotifier:
    webhook_url: str
    timeout_seconds: int = 10
    retry_count: int = 1

    def send(self, message: str) -> None:
        payload = json.dumps({"content": message}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        last_error: Exception | None = None

        for attempt in range(self.retry_count + 1):
            req = request.Request(self.webhook_url, data=payload, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout_seconds):
                    return
            except (HTTPError, URLError, RuntimeError) as exc:
                last_error = exc
                LOGGER.error("Discord通知失敗 (attempt=%s): %s", attempt + 1, exc)
                continue

        raise DiscordNotifyError(f"Discord通知に失敗しました: {last_error}")
