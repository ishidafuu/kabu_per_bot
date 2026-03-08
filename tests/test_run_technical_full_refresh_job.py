from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.run_technical_full_refresh_job as target


class TechnicalFullRefreshJobScriptTest(unittest.TestCase):
    def test_main_forces_full_refresh_and_skip_alerts(self) -> None:
        with patch.object(target.daily_job, "_run", return_value=0) as mocked_run:
            code = target.main()

        self.assertEqual(code, 0)
        self.assertEqual(
            mocked_run.call_args.kwargs,
            {
                "job_name": "technical_full_refresh",
                "force_full_refresh": True,
                "force_skip_alerts": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
