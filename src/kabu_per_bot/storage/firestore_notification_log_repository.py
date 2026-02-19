from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
from typing import Any

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import COLLECTION_JOB_RUN, COLLECTION_NOTIFICATION_LOG, normalize_ticker

EARNINGS_JOB_NAME_PREFIX = "earnings_"
LOGGER = logging.getLogger(__name__)
_MISSING_INDEX_WARNING_KEYS: set[str] = set()


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
        category: str | None = None,
        is_strong: bool | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        normalized_category = _normalize_category(category)
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where") and hasattr(self._collection, "order_by"):
            try:
                query = self._collection
                if normalized_ticker:
                    query = query.where("ticker", "==", normalized_ticker)
                if normalized_category:
                    query = query.where("category", "==", normalized_category)
                if is_strong is not None:
                    query = query.where("is_strong", "==", is_strong)
                if sent_at_from is not None:
                    query = query.where("sent_at", ">=", sent_at_from)
                if sent_at_to is not None:
                    query = query.where("sent_at", "<", sent_at_to)
                query = query.order_by("sent_at", direction="DESCENDING")
                if offset > 0 and hasattr(query, "offset"):
                    query = query.offset(offset)
                if limit is not None and hasattr(query, "limit"):
                    query = query.limit(limit)
                rows = [NotificationLogEntry.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]
                return _filter_sort_paginate_rows(
                    rows=rows,
                    from_dt=from_dt,
                    to_dt=to_dt,
                    limit=limit,
                    offset=offset,
                    normalized_category=normalized_category,
                    is_strong=is_strong,
                )
            except Exception as exc:
                if not _is_missing_index_error(exc):
                    raise
                _log_missing_index_warning_once(key="timeline.primary", exc=exc)

                reduced_rows = _try_list_timeline_with_reduced_query(
                    collection=self._collection,
                    normalized_ticker=normalized_ticker,
                    normalized_category=normalized_category,
                    is_strong=is_strong,
                    sent_at_from=sent_at_from,
                    sent_at_to=sent_at_to,
                    from_dt=from_dt,
                    to_dt=to_dt,
                    limit=limit,
                    offset=offset,
                )
                if reduced_rows is not None:
                    return reduced_rows

        return _list_timeline_in_memory(
            collection=self._collection,
            normalized_ticker=normalized_ticker,
            normalized_category=normalized_category,
            is_strong=is_strong,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
        )

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        category: str | None = None,
        is_strong: bool | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        normalized_category = _normalize_category(category)
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where"):
            try:
                query = self._collection
                if normalized_ticker:
                    query = query.where("ticker", "==", normalized_ticker)
                if normalized_category:
                    query = query.where("category", "==", normalized_category)
                if is_strong is not None:
                    query = query.where("is_strong", "==", is_strong)
                if sent_at_from is not None:
                    query = query.where("sent_at", ">=", sent_at_from)
                if sent_at_to is not None:
                    query = query.where("sent_at", "<", sent_at_to)
                rows = [NotificationLogEntry.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]
                filtered = _filter_sort_paginate_rows(
                    rows=rows,
                    from_dt=from_dt,
                    to_dt=to_dt,
                    limit=None,
                    offset=0,
                    normalized_category=normalized_category,
                    is_strong=is_strong,
                )
                return len(filtered)
            except Exception as exc:
                if not _is_missing_index_error(exc):
                    raise
                _log_missing_index_warning_once(key="count.primary", exc=exc)

        return _count_timeline_in_memory(
            collection=self._collection,
            normalized_ticker=normalized_ticker,
            normalized_category=normalized_category,
            is_strong=is_strong,
            from_dt=from_dt,
            to_dt=to_dt,
        )

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
            return any(_is_dashboard_target_job(snapshot.to_dict() or {}) for snapshot in query.stream())

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
            if _is_dashboard_target_job(data):
                return True
        return False

    def reset_grok_sns_cooldown(self, *, ticker: str | None = None) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        targets: list[Any] = []
        if hasattr(self._collection, "where"):
            try:
                query = self._collection.where("category", "==", "SNS注目")
                if normalized_ticker:
                    query = query.where("ticker", "==", normalized_ticker)
                targets = list(query.stream())
            except Exception as exc:
                if not _is_missing_index_error(exc):
                    raise
                _log_missing_index_warning_once(key="reset_grok_cooldown.primary", exc=exc)

        if not targets:
            for snapshot in self._collection.stream():
                data = snapshot.to_dict() or {}
                if str(data.get("category", "")).strip() != "SNS注目":
                    continue
                if normalized_ticker and str(data.get("ticker", "")).strip().upper() != normalized_ticker:
                    continue
                targets.append(snapshot)

        deleted = 0
        for snapshot in targets:
            snapshot.reference.delete()
            deleted += 1
        return deleted


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


def _is_dashboard_target_job(data: dict[str, Any]) -> bool:
    job_name = str(data.get("job_name", "")).strip()
    if not job_name.startswith(EARNINGS_JOB_NAME_PREFIX):
        return False
    return _is_failed_job_document(data)


def _is_missing_index_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return "requires an index" in lowered


def _normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    normalized = category.strip()
    if not normalized:
        return None
    return normalized


def _log_missing_index_warning_once(*, key: str, exc: Exception) -> None:
    if key in _MISSING_INDEX_WARNING_KEYS:
        return
    _MISSING_INDEX_WARNING_KEYS.add(key)
    LOGGER.warning("notification_log query index不足のためフォールバック: %s", exc)


def _try_list_timeline_with_reduced_query(
    *,
    collection: Any,
    normalized_ticker: str | None,
    normalized_category: str | None,
    is_strong: bool | None,
    sent_at_from: str | None,
    sent_at_to: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    limit: int | None,
    offset: int,
) -> list[NotificationLogEntry] | None:
    if not hasattr(collection, "where"):
        return None
    try:
        query = collection
        if normalized_ticker:
            query = query.where("ticker", "==", normalized_ticker)
        if normalized_category:
            query = query.where("category", "==", normalized_category)
        if is_strong is not None:
            query = query.where("is_strong", "==", is_strong)
        if sent_at_from is not None:
            query = query.where("sent_at", ">=", sent_at_from)
        if sent_at_to is not None:
            query = query.where("sent_at", "<", sent_at_to)
        rows = [NotificationLogEntry.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]
        rows = _filter_sort_paginate_rows(
            rows=rows,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
            normalized_category=normalized_category,
            is_strong=is_strong,
        )
        return rows
    except Exception as exc:
        if not _is_missing_index_error(exc):
            raise
        _log_missing_index_warning_once(key="timeline.reduced", exc=exc)
        return None


def _list_timeline_in_memory(
    *,
    collection: Any,
    normalized_ticker: str | None,
    normalized_category: str | None,
    is_strong: bool | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    limit: int | None,
    offset: int,
) -> list[NotificationLogEntry]:
    rows: list[NotificationLogEntry] = []
    for snapshot in collection.stream():
        data = snapshot.to_dict() or {}
        if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
            continue
        row = NotificationLogEntry.from_document(data)
        if not _matches_notification_row(
            row=row,
            from_dt=from_dt,
            to_dt=to_dt,
            normalized_category=normalized_category,
            is_strong=is_strong,
        ):
            continue
        rows.append(row)
    return _filter_sort_paginate_rows(
        rows=rows,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
        normalized_category=normalized_category,
        is_strong=is_strong,
    )


def _count_timeline_in_memory(
    *,
    collection: Any,
    normalized_ticker: str | None,
    normalized_category: str | None,
    is_strong: bool | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> int:
    count = 0
    for snapshot in collection.stream():
        data = snapshot.to_dict() or {}
        if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
            continue
        row = NotificationLogEntry.from_document(data)
        if not _matches_notification_row(
            row=row,
            from_dt=from_dt,
            to_dt=to_dt,
            normalized_category=normalized_category,
            is_strong=is_strong,
        ):
            continue
        count += 1
    return count


def _filter_sort_paginate_rows(
    *,
    rows: list[NotificationLogEntry],
    from_dt: datetime | None,
    to_dt: datetime | None,
    limit: int | None,
    offset: int,
    normalized_category: str | None,
    is_strong: bool | None,
) -> list[NotificationLogEntry]:
    filtered: list[NotificationLogEntry] = []
    for row in rows:
        if not _matches_notification_row(
            row=row,
            from_dt=from_dt,
            to_dt=to_dt,
            normalized_category=normalized_category,
            is_strong=is_strong,
        ):
            continue
        filtered.append(row)
    filtered.sort(key=lambda row: _parse_iso_datetime(row.sent_at), reverse=True)
    if limit is None:
        return filtered[offset:]
    return filtered[offset : offset + limit]


def _matches_notification_row(
    *,
    row: NotificationLogEntry,
    from_dt: datetime | None,
    to_dt: datetime | None,
    normalized_category: str | None,
    is_strong: bool | None,
) -> bool:
    if normalized_category and row.category != normalized_category:
        return False
    if is_strong is not None and row.is_strong is not is_strong:
        return False
    sent_at = _parse_iso_datetime(row.sent_at)
    if from_dt is not None and sent_at < from_dt:
        return False
    if to_dt is not None and sent_at >= to_dt:
        return False
    return True
