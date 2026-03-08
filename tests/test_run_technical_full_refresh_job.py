from __future__ import annotations

import importlib
import sys
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

    def test_module_import_fallback_works_without_scripts_package(self) -> None:
        script_module = sys.modules.pop("scripts.run_technical_daily_job", None)
        top_level_module = sys.modules.get("run_technical_daily_job")
        try:
            sys.modules["run_technical_daily_job"] = target.daily_job
            reloaded = importlib.reload(target)
            self.assertIs(reloaded.daily_job, target.daily_job)
        finally:
            if script_module is not None:
                sys.modules["scripts.run_technical_daily_job"] = script_module
            else:
                sys.modules.pop("scripts.run_technical_daily_job", None)
            if top_level_module is not None:
                sys.modules["run_technical_daily_job"] = top_level_module
            else:
                sys.modules.pop("run_technical_daily_job", None)
            importlib.reload(target)


if __name__ == "__main__":
    unittest.main()
