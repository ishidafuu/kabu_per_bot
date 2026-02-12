from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from kabu_per_bot.discord_notifier import DiscordNotifier, DiscordNotifyError


class DiscordNotifierTest(unittest.TestCase):
    def test_send_success(self) -> None:
        notifier = DiscordNotifier(webhook_url="https://example.com/webhook", retry_count=1)
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("kabu_per_bot.discord_notifier.request.urlopen", return_value=response) as mocked:
            notifier.send("hello")
        self.assertEqual(mocked.call_count, 1)

    def test_send_retry_and_fail(self) -> None:
        notifier = DiscordNotifier(webhook_url="https://example.com/webhook", retry_count=1)
        with patch("kabu_per_bot.discord_notifier.request.urlopen", side_effect=RuntimeError("boom")) as mocked:
            with self.assertRaises(DiscordNotifyError):
                notifier.send("hello")
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
