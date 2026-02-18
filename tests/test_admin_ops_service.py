from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from kabu_per_bot.admin_ops import AdminOpsJob, CloudRunAdminOpsService, JobExecution


def _execution(*, name: str, status: str, created_at: str) -> JobExecution:
    return JobExecution(
        job_key="daily",
        job_label="日次ジョブ（IMMEDIATE）",
        job_name="kabu-daily",
        execution_name=name,
        status=status,
        create_time=created_at,
        start_time=created_at,
        completion_time=None,
        message=None,
        log_uri=None,
        skip_reasons=(),
        skip_reason_error=None,
    )


class AdminOpsServiceTest(unittest.TestCase):
    def test_run_job_waits_for_new_execution(self) -> None:
        service = object.__new__(CloudRunAdminOpsService)
        job = AdminOpsJob(key="daily", label="日次", job_name="kabu-daily")
        service._jobs = (job,)
        service._job_index = {"daily": job}
        service._base_run_url = "https://example.com"
        service._request_json = Mock(return_value={})

        old = _execution(name="old", status="SUCCEEDED", created_at="2026-01-01T00:00:00+00:00")
        new = _execution(name="new", status="PENDING", created_at=datetime.now(timezone.utc).isoformat())
        service.list_executions = Mock(side_effect=[(old,), (old,), (new,)])

        with patch("kabu_per_bot.admin_ops.time.sleep", return_value=None):
            actual = service.run_job(job_key="daily")

        self.assertEqual(actual.execution_name, "new")
        self.assertEqual(service._request_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()
