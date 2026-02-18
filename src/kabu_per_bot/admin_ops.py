from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
import time
from typing import Any

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_RUNNING_STATUSES = {"PENDING", "RUNNING"}
_DAILY_JOB_KEYS = {"daily", "daily_at21"}


class AdminOpsError(RuntimeError):
    """Base error for admin operations."""


class AdminOpsConfigError(AdminOpsError):
    """Raised when admin operations configuration is invalid."""


class AdminOpsNotFoundError(AdminOpsError):
    """Raised when requested resource is not found."""


class AdminOpsConflictError(AdminOpsError):
    """Raised when requested operation conflicts with current state."""


@dataclass(frozen=True)
class BackfillRunRequest:
    from_date: str
    to_date: str
    tickers: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class AdminOpsJob:
    key: str
    label: str
    job_name: str | None

    @property
    def configured(self) -> bool:
        return bool(self.job_name)


@dataclass(frozen=True)
class SkipReasonCount:
    reason: str
    count: int


@dataclass(frozen=True)
class JobExecution:
    job_key: str
    job_label: str
    job_name: str
    execution_name: str
    status: str
    create_time: str | None
    start_time: str | None
    completion_time: str | None
    message: str | None
    log_uri: str | None
    skip_reasons: tuple[SkipReasonCount, ...]
    skip_reason_error: str | None


@dataclass(frozen=True)
class AdminOpsSummary:
    jobs: tuple[AdminOpsJob, ...]
    recent_executions: tuple[JobExecution, ...]
    latest_skip_reasons: tuple[JobExecution, ...]


class CloudRunAdminOpsService:
    def __init__(
        self,
        *,
        project_id: str | None = None,
        region: str | None = None,
        jobs: tuple[AdminOpsJob, ...] | None = None,
    ) -> None:
        self._region = (region or os.getenv("OPS_GCP_REGION", "asia-northeast1")).strip() or "asia-northeast1"
        self._project_id = (
            (project_id or os.getenv("OPS_GCP_PROJECT_ID", "")).strip()
            or os.getenv("FIRESTORE_PROJECT_ID", "").strip()
        )
        if not self._project_id:
            raise AdminOpsConfigError("OPS_GCP_PROJECT_ID または FIRESTORE_PROJECT_ID を設定してください。")
        self._jobs = jobs or _load_default_jobs()
        self._job_index = {job.key: job for job in self._jobs}
        self._session = _create_authorized_session()
        self._base_run_url = f"https://run.googleapis.com/v2/projects/{self._project_id}/locations/{self._region}"
        self._base_logging_url = "https://logging.googleapis.com/v2/entries:list"

    def list_jobs(self) -> tuple[AdminOpsJob, ...]:
        return self._jobs

    def run_job(self, *, job_key: str, backfill: BackfillRunRequest | None = None) -> JobExecution:
        job = self._resolve_job(job_key)
        job_name = self._require_job_name(job)
        if self._has_running_execution(job_key=job.key):
            raise AdminOpsConflictError(f"job={job_name} は既に実行中です。完了後に再実行してください。")

        payload: dict[str, Any] = {}
        if job.key == "backfill":
            if backfill is None:
                raise AdminOpsConfigError("backfill 実行には from/to の指定が必要です。")
            payload = {"overrides": {"containerOverrides": [{"args": _build_backfill_args(backfill)}]}}
        elif backfill is not None:
            raise AdminOpsConfigError("backfill指定は job=backfill でのみ使用できます。")

        self._request_json(
            method="POST",
            url=f"{self._base_run_url}/jobs/{job_name}:run",
            payload=payload if payload else {},
        )
        time.sleep(0.7)
        latest = self.list_executions(job_key=job_key, limit=1)
        if not latest:
            raise AdminOpsError(f"job={job_name} の実行開始を確認できませんでした。")
        return latest[0]

    def list_executions(self, *, job_key: str, limit: int = 20) -> tuple[JobExecution, ...]:
        job = self._resolve_job(job_key)
        job_name = self._require_job_name(job)
        payload = self._request_json(
            method="GET",
            url=f"{self._base_run_url}/jobs/{job_name}/executions?pageSize={limit}",
            payload=None,
            allow_not_found=False,
        )
        rows = payload.get("executions", [])
        if not isinstance(rows, list):
            return ()
        return tuple(self._parse_execution(job=job, data=row, include_skip_reasons=False) for row in rows)

    def get_summary(self, *, limit_per_job: int = 5) -> AdminOpsSummary:
        recent: list[JobExecution] = []
        latest_skip_rows: list[JobExecution] = []
        for job in self._jobs:
            if not job.configured:
                continue
            try:
                executions = list(self.list_executions(job_key=job.key, limit=limit_per_job))
            except Exception as exc:
                recent.append(
                    JobExecution(
                        job_key=job.key,
                        job_label=job.label,
                        job_name=job.job_name or "",
                        execution_name="",
                        status="FAILED",
                        create_time=datetime.now(timezone.utc).isoformat(),
                        start_time=None,
                        completion_time=None,
                        message=f"実行履歴取得失敗: {exc}",
                        log_uri=None,
                        skip_reasons=(),
                        skip_reason_error=None,
                    )
                )
                continue
            recent.extend(executions)
            if job.key in _DAILY_JOB_KEYS and executions:
                latest = executions[0]
                latest_skip_rows.append(self._attach_skip_reasons(job=job, execution=latest))

        recent.sort(key=lambda row: _sortable_iso(row.create_time), reverse=True)
        latest_skip_rows.sort(key=lambda row: _sortable_iso(row.create_time), reverse=True)
        return AdminOpsSummary(
            jobs=self._jobs,
            recent_executions=tuple(recent),
            latest_skip_reasons=tuple(latest_skip_rows),
        )

    def send_discord_test(self, *, requested_uid: str) -> str:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise AdminOpsConfigError("DISCORD_WEBHOOK_URL が未設定です。")
        now_iso = datetime.now(timezone.utc).isoformat()
        message = (
            "【疎通テスト】\n"
            "管理画面からDiscord通知テストを実行しました。\n"
            f"requested_uid: {requested_uid}\n"
            f"sent_at: {now_iso}"
        )
        notifier = DiscordNotifier(webhook_url)
        notifier.send(message)
        return now_iso

    def _resolve_job(self, job_key: str) -> AdminOpsJob:
        key = str(job_key).strip().lower()
        job = self._job_index.get(key)
        if job is None:
            raise AdminOpsNotFoundError(f"不明なjob_keyです: {job_key}")
        return job

    def _require_job_name(self, job: AdminOpsJob) -> str:
        if job.job_name is None or not job.job_name.strip():
            raise AdminOpsConfigError(f"job={job.key} の設定がありません。")
        return job.job_name

    def _has_running_execution(self, *, job_key: str) -> bool:
        executions = self.list_executions(job_key=job_key, limit=10)
        return any(row.status in _RUNNING_STATUSES for row in executions)

    def _attach_skip_reasons(self, *, job: AdminOpsJob, execution: JobExecution) -> JobExecution:
        if execution.execution_name == "":
            return execution
        try:
            counts = self._list_skip_reasons(job_name=execution.job_name, execution_name=execution.execution_name)
            skip_counts = tuple(SkipReasonCount(reason=key, count=value) for key, value in counts.items())
            return JobExecution(
                job_key=execution.job_key,
                job_label=execution.job_label,
                job_name=execution.job_name,
                execution_name=execution.execution_name,
                status=execution.status,
                create_time=execution.create_time,
                start_time=execution.start_time,
                completion_time=execution.completion_time,
                message=execution.message,
                log_uri=execution.log_uri,
                skip_reasons=skip_counts,
                skip_reason_error=None,
            )
        except Exception as exc:
            return JobExecution(
                job_key=execution.job_key,
                job_label=execution.job_label,
                job_name=execution.job_name,
                execution_name=execution.execution_name,
                status=execution.status,
                create_time=execution.create_time,
                start_time=execution.start_time,
                completion_time=execution.completion_time,
                message=execution.message,
                log_uri=execution.log_uri,
                skip_reasons=(),
                skip_reason_error=f"スキップ理由集計に失敗しました: {exc}",
            )

    def _list_skip_reasons(self, *, job_name: str, execution_name: str) -> dict[str, int]:
        filter_expr = (
            f'resource.type="cloud_run_job" '
            f'AND resource.labels.job_name="{job_name}" '
            f'AND labels."run.googleapis.com/execution_name"="{execution_name}" '
            'AND textPayload:"通知スキップ:"'
        )
        payload = {
            "resourceNames": [f"projects/{self._project_id}"],
            "filter": filter_expr,
            "orderBy": "timestamp desc",
            "pageSize": 300,
        }
        response = self._request_json(
            method="POST",
            url=self._base_logging_url,
            payload=payload,
        )
        reason_counts: dict[str, int] = {}
        entries = response.get("entries", [])
        if not isinstance(entries, list):
            return {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("textPayload", "")).strip()
            reason = _extract_skip_reason(text)
            if reason is None:
                continue
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        return dict(sorted(reason_counts.items(), key=lambda row: row[1], reverse=True))

    def _parse_execution(self, *, job: AdminOpsJob, data: Any, include_skip_reasons: bool) -> JobExecution:
        if not isinstance(data, dict):
            raise AdminOpsError(f"executionレスポンスが不正です: {data!r}")
        full_name = str(data.get("name", ""))
        execution_name = full_name.rsplit("/", 1)[-1] if full_name else ""
        status, message = _resolve_execution_status(data)
        row = JobExecution(
            job_key=job.key,
            job_label=job.label,
            job_name=job.job_name or "",
            execution_name=execution_name,
            status=status,
            create_time=_as_iso_or_none(data.get("createTime")),
            start_time=_as_iso_or_none(data.get("startTime")),
            completion_time=_as_iso_or_none(data.get("completionTime")),
            message=message,
            log_uri=_as_non_empty_str_or_none(data.get("logUri")),
            skip_reasons=(),
            skip_reason_error=None,
        )
        if include_skip_reasons:
            return self._attach_skip_reasons(job=job, execution=row)
        return row

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"timeout": 35}
        if payload is not None:
            request_kwargs["json"] = payload
        response = self._session.request(method=method, url=url, **request_kwargs)
        if response.status_code == 404 and allow_not_found:
            return {}
        if response.status_code >= 400:
            text = response.text.strip()
            if response.status_code == 404:
                raise AdminOpsNotFoundError(f"API resource not found: {url}")
            raise AdminOpsError(f"API request failed: {response.status_code} {text}")
        if not response.content:
            return {}
        body = response.json()
        if not isinstance(body, dict):
            return {}
        return body


def _create_authorized_session():
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
    except ModuleNotFoundError as exc:
        raise AdminOpsConfigError(
            "google-auth が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    return AuthorizedSession(credentials)


def _load_default_jobs() -> tuple[AdminOpsJob, ...]:
    return (
        AdminOpsJob(
            key="daily",
            label="日次ジョブ（IMMEDIATE）",
            job_name=_env_or_default("OPS_DAILY_JOB_NAME", "kabu-daily"),
        ),
        AdminOpsJob(
            key="daily_at21",
            label="21:05ジョブ（AT_21）",
            job_name=_env_or_default("OPS_DAILY_AT21_JOB_NAME", "kabu-daily-at21"),
        ),
        AdminOpsJob(
            key="earnings_weekly",
            label="今週決算ジョブ",
            job_name=_env_or_default("OPS_EARNINGS_WEEKLY_JOB_NAME", "kabu-earnings-weekly"),
        ),
        AdminOpsJob(
            key="earnings_tomorrow",
            label="明日決算ジョブ",
            job_name=_env_or_default("OPS_EARNINGS_TOMORROW_JOB_NAME", "kabu-earnings-tomorrow"),
        ),
        AdminOpsJob(
            key="backfill",
            label="バックフィルジョブ",
            job_name=_env_or_default("OPS_BACKFILL_JOB_NAME", ""),
        ),
    )


def _env_or_default(key: str, default: str) -> str | None:
    value = os.getenv(key, default).strip()
    if not value:
        return None
    return value


def _resolve_execution_status(data: dict[str, Any]) -> tuple[str, str | None]:
    completed_state: str | None = None
    completed_message: str | None = None
    for row in data.get("conditions", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("type", "")) != "Completed":
            continue
        completed_state = str(row.get("state", ""))
        completed_message = _as_non_empty_str_or_none(row.get("message"))
        break
    if completed_state == "CONDITION_SUCCEEDED":
        return "SUCCEEDED", completed_message
    if completed_state == "CONDITION_FAILED":
        return "FAILED", completed_message
    if _as_iso_or_none(data.get("completionTime")):
        return "FAILED", completed_message
    if _as_iso_or_none(data.get("startTime")):
        return "RUNNING", completed_message
    return "PENDING", completed_message


def _as_iso_or_none(value: Any) -> str | None:
    text = _as_non_empty_str_or_none(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return text


def _as_non_empty_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _extract_skip_reason(text: str) -> str | None:
    if "通知スキップ:" not in text:
        return None
    match = re.search(r"reason=(.+)$", text)
    if match:
        return match.group(1).strip() or "不明"
    return "不明"


def _sortable_iso(value: str | None) -> str:
    return value or ""


def _build_backfill_args(request: BackfillRunRequest) -> list[str]:
    try:
        from_date = normalize_trade_date(request.from_date)
        to_date = normalize_trade_date(request.to_date)
    except ValueError as exc:
        raise AdminOpsConfigError(str(exc)) from exc
    if from_date > to_date:
        raise AdminOpsConfigError("from_date は to_date 以下で指定してください。")
    args = [
        "scripts/run_backfill_daily_metrics.py",
        "--from-date",
        from_date,
        "--to-date",
        to_date,
    ]
    if request.tickers:
        try:
            normalized = [normalize_ticker(ticker) for ticker in request.tickers]
        except ValueError as exc:
            raise AdminOpsConfigError(str(exc)) from exc
        args.extend(["--tickers", ",".join(normalized)])
    if request.dry_run:
        args.append("--dry-run")
    return args
