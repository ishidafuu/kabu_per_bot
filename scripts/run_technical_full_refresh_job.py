#!/usr/bin/env python3
from __future__ import annotations

import logging

try:
    import scripts.run_technical_daily_job as daily_job
except ModuleNotFoundError:
    import run_technical_daily_job as daily_job


LOGGER = logging.getLogger(__name__)


def main() -> int:
    return daily_job._run(
        job_name="technical_full_refresh",
        force_full_refresh=True,
        force_skip_alerts=True,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("technical full refresh job failed: %s", exc)
        raise SystemExit(1) from exc
