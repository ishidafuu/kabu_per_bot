from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import COLLECTION_JOB_RUN, COLLECTION_NOTIFICATION_LOG, normalize_ticker


class FirestoreNotificationLogRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_NOTIFICATION_LOG)
        self._job_run_collection = client.collection(COLLECTION_JOB_RUN)

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
        normalized_status = _normalize_job_status(status)
        job_name_value = job_name.strip()
        if not job_name_value:
            raise ValueError("job_name is required")
        if error_count < 0:
            raise ValueError("error_count must be >= 0")
        row = {
            "job_name": job_name_value,
            "started_at": _parse_iso_datetime(started_at).astimezone(timezone.utc).isoformat(),
            "finished_at": _parse_iso_datetime(finished_at).astimezone(timezone.utc).isoformat(),
            "status": normalized_status,
            "error_count": error_count,
            "failed": normalized_status == "FAILED",
        }
        if detail:
            row["detail"] = detail.strip()
        doc_id = _build_job_run_doc_id(
            job_name=row["job_name"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
        self._job_run_collection.document(doc_id).set(row, merge=False)

    def append(self, entry: NotificationLogEntry) -> None:
        self._collection.document(entry.entry_id).set(entry.to_document(), merge=False)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        return self.list_timeline(ticker=ticker, limit=limit)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where") and hasattr(self._collection, "order_by"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            if sent_at_from is not None:
                query = query.where("sent_at", ">=", sent_at_from)
            if sent_at_to is not None:
                query = query.where("sent_at", "<", sent_at_to)
            query = query.order_by("sent_at", direction="DESCENDING")
            if offset > 0 and hasattr(query, "offset"):
                query = query.offset(offset)
            if limit is not None and hasattr(query, "limit"):
                query = query.limit(limit)
            return [NotificationLogEntry.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]

        rows: list[NotificationLogEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            row = NotificationLogEntry.from_document(data)
            sent_at = _parse_iso_datetime(row.sent_at)
            if from_dt is not None and sent_at < from_dt:
                continue
            if to_dt is not None and sent_at >= to_dt:
                continue
            rows.append(row)
        rows.sort(key=lambda row: _parse_iso_datetime(row.sent_at), reverse=True)
        if limit is None:
            return rows[offset:]
        return rows[offset : offset + limit]

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            if sent_at_from is not None:
                query = query.where("sent_at", ">=", sent_at_from)
            if sent_at_to is not None:
                query = query.where("sent_at", "<", sent_at_to)
            return sum(1 for _ in query.stream())

        count = 0
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            sent_at_raw = data.get("sent_at")
            if sent_at_raw is None:
                continue
            sent_at = _parse_iso_datetime(str(sent_at_raw))
            if from_dt is not None and sent_at < from_dt:
                continue
            if to_dt is not None and sent_at >= to_dt:
                continue
            count += 1
        return count

    def failed_job_exists(
        self,
        *,
        sent_at_from: str,
        sent_at_to: str,
    ) -> bool:
        from_dt = _parse_iso_datetime(sent_at_from)
        to_dt = _parse_iso_datetime(sent_at_to)

        if hasattr(self._job_run_collection, "where") and hasattr(self._job_run_collection, "order_by"):
            query = self._job_run_collection
            query = query.where("started_at", ">=", sent_at_from)
            query = query.where("started_at", "<", sent_at_to)
            query = query.order_by("started_at", direction="DESCENDING")
            return any(_is_failed_job_document(snapshot.to_dict() or {}) for snapshot in query.stream())

        for snapshot in self._job_run_collection.stream():
            data = snapshot.to_dict() or {}
            started_at_raw = data.get("started_at")
            if started_at_raw is None:
                continue
            started_at = _parse_iso_datetime(str(started_at_raw))
            if started_at < from_dt:
                continue
            if started_at >= to_dt:
                continue
            if _is_failed_job_document(data):
                return True
        return False


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_job_status(status: str) -> str:
    normalized = status.strip().upper()
    if normalized not in {"SUCCESS", "FAILED"}:
        raise ValueError("status must be SUCCESS or FAILED")
    return normalized


def _build_job_run_doc_id(*, job_name: str, started_at: str, finished_at: str) -> str:
    raw = f"{job_name}|{started_at}|{finished_at}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    safe_job_name = job_name.strip().replace("/", "_").replace(" ", "_") or "job"
    return f"{safe_job_name}|{digest}"


def _is_failed_job_document(data: dict[str, Any]) -> bool:
    status = str(data.get("status", "")).strip().upper()
    if status == "FAILED":
        return True
    if status == "SUCCESS":
        return False

    failed = data.get("failed")
    if isinstance(failed, bool):
        return failed

    error_count = data.get("error_count")
    if error_count is None:
        return False
    try:
        return int(error_count) > 0
    except (TypeError, ValueError):
        return False
