from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts.run_earnings_job as target


@dataclass
class _FakeLogRepository:
    append_calls: list[dict] | None = None
    raise_on_append: bool = False

    def __post_init__(self) -> None:
        if self.append_calls is None:
            self.append_calls = []

    def append_job_run(
        self,
        *,
        job_name: str,
        started_at: str,
        finished_at: str,
        status: str,
        error_count: int = 0,
        detail: str | None = None,
    ) -> None:
        if self.raise_on_append:
            raise RuntimeError("append failed")
        self.append_calls.append(
            {
                "job_name": job_name,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "error_count": error_count,
                "detail": detail,
            }
        )


class RunEarningsJobScriptTest(unittest.TestCase):
    def test_main_records_success_with_now_iso_timestamp(self) -> None:
        fake_log_repo = _FakeLogRepository()
        args = SimpleNamespace(
            job="weekly",
            now_iso="2026-02-14T21:00:00+09:00",
            discord_webhook_url="",
            stdout=True,
        )
        settings = SimpleNamespace(firestore_project_id="demo-project", cooldown_hours=2)
        result = SimpleNamespace(
            processed_tickers=1,
            sent_notifications=0,
            skipped_notifications=0,
            errors=0,
        )

        with (
            patch.object(target, "parse_args", return_value=args),
            patch.object(target, "load_settings", return_value=settings),
            patch.object(target, "_create_firestore_client", return_value=object()),
            patch.object(target, "FirestoreWatchlistRepository", return_value=object()),
            patch.object(target, "FirestoreEarningsCalendarRepository", return_value=object()),
            patch.object(target, "FirestoreNotificationLogRepository", return_value=fake_log_repo),
            patch.object(target, "run_earnings_job", return_value=result),
        ):
            exit_code = target.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_log_repo.append_calls or []), 1)
        call = (fake_log_repo.append_calls or [])[0]
        self.assertEqual(call["status"], "SUCCESS")
        self.assertEqual(call["started_at"], "2026-02-14T12:00:00+00:00")
        self.assertEqual(call["finished_at"], "2026-02-14T12:00:00+00:00")

    def test_main_records_failure_when_webhook_validation_fails(self) -> None:
        fake_log_repo = _FakeLogRepository()
        args = SimpleNamespace(
            job="weekly",
            now_iso="2026-02-14T21:00:00+09:00",
            discord_webhook_url="",
            stdout=False,
        )
        settings = SimpleNamespace(firestore_project_id="demo-project", cooldown_hours=2)

        with (
            patch.object(target, "parse_args", return_value=args),
            patch.object(target, "load_settings", return_value=settings),
            patch.object(target, "_create_firestore_client", return_value=object()),
            patch.object(target, "FirestoreWatchlistRepository", return_value=object()),
            patch.object(target, "FirestoreEarningsCalendarRepository", return_value=object()),
            patch.object(target, "FirestoreNotificationLogRepository", return_value=fake_log_repo),
        ):
            with self.assertRaisesRegex(ValueError, "Discord webhook URL"):
                target.main()

        self.assertEqual(len(fake_log_repo.append_calls or []), 1)
        call = (fake_log_repo.append_calls or [])[0]
        self.assertEqual(call["status"], "FAILED")
        self.assertEqual(call["job_name"], "earnings_weekly")

    def test_main_keeps_original_error_when_job_run_save_fails(self) -> None:
        fake_log_repo = _FakeLogRepository(raise_on_append=True)
        args = SimpleNamespace(
            job="weekly",
            now_iso="2026-02-14T21:00:00+09:00",
            discord_webhook_url="",
            stdout=True,
        )
        settings = SimpleNamespace(firestore_project_id="demo-project", cooldown_hours=2)

        with (
            patch.object(target, "parse_args", return_value=args),
            patch.object(target, "load_settings", return_value=settings),
            patch.object(target, "_create_firestore_client", return_value=object()),
            patch.object(target, "FirestoreWatchlistRepository", return_value=object()),
            patch.object(target, "FirestoreEarningsCalendarRepository", return_value=object()),
            patch.object(target, "FirestoreNotificationLogRepository", return_value=fake_log_repo),
            patch.object(target, "run_earnings_job", side_effect=RuntimeError("job failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "job failed"):
                target.main()


if __name__ == "__main__":
    unittest.main()
