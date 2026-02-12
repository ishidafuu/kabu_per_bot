from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.earnings import (
    EarningsCalendarEntry,
    EarningsCalendarSyncError,
    select_next_week_entries,
    select_tomorrow_entries,
    sync_earnings_calendar_for_ticker,
)
from kabu_per_bot.storage.firestore_earnings_calendar_repository import FirestoreEarningsCalendarRepository


@dataclass
class FakeSnapshot:
    exists: bool
    data: dict | None = None

    def to_dict(self) -> dict | None:
        return self.data


@dataclass
class FakeDocumentRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def set(self, data: dict, merge: bool = False) -> None:
        self.db[self.path] = dict(data)

    def delete(self) -> None:
        if self.path in self.db:
            del self.db[self.path]


@dataclass
class FakeCollectionRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def document(self, document_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(path=f"{self.path}/{document_id}", db=self.db)

    def stream(self) -> list[FakeSnapshot]:
        prefix = f"{self.path}/"
        return [
            FakeSnapshot(exists=True, data=dict(value))
            for key, value in self.db.items()
            if key.startswith(prefix)
        ]


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


class StaticEarningsSource:
    def __init__(self, source_name: str, rows: list[dict]) -> None:
        self.source_name = source_name
        self._rows = list(rows)

    def fetch_earnings_calendar(self, ticker: str) -> list[dict]:
        _ = ticker
        return list(self._rows)


class FailingEarningsSource:
    def __init__(self, source_name: str = "失敗ソース") -> None:
        self.source_name = source_name

    def fetch_earnings_calendar(self, ticker: str) -> list[dict]:
        raise RuntimeError(f"failed for {ticker}")


class InvalidPayloadEarningsSource:
    def __init__(self, source_name: str = "不正ソース") -> None:
        self.source_name = source_name

    def fetch_earnings_calendar(self, ticker: str) -> list[dict]:
        _ = ticker
        return None  # type: ignore[return-value]


class EarningsTest(unittest.TestCase):
    def test_select_next_week_entries(self) -> None:
        entries = [
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-16",
                earnings_time="15:00",
                quarter="3Q",
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
            EarningsCalendarEntry(
                ticker="3902:TSE",
                earnings_date="2026-02-25",
                earnings_time=None,
                quarter=None,
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
        ]
        # 2026-02-14(土) の来週は 2026-02-16(月)〜2026-02-22(日)
        selected = select_next_week_entries(entries, today="2026-02-14")
        self.assertEqual([entry.ticker for entry in selected], ["3901:TSE"])

    def test_select_tomorrow_entries(self) -> None:
        entries = [
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-13",
                earnings_time="15:00",
                quarter="3Q",
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
            EarningsCalendarEntry(
                ticker="3902:TSE",
                earnings_date="2026-02-14",
                earnings_time=None,
                quarter=None,
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
        ]
        selected = select_tomorrow_entries(entries, today="2026-02-12")
        self.assertEqual([entry.ticker for entry in selected], ["3901:TSE"])

    def test_sync_saves_entries_by_ticker(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        source = StaticEarningsSource(
            source_name="株探",
            rows=[
                {
                    "earnings_date": "2026-02-13",
                    "earnings_time": "15:00",
                    "quarter": "3Q",
                }
            ],
        )

        saved = sync_earnings_calendar_for_ticker(
            ticker="3901:tse",
            source=source,
            repository=repo,
            fetched_at="2026-02-12T00:00:00+00:00",
        )

        self.assertEqual(len(saved), 1)
        rows = repo.list_by_ticker("3901:TSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ticker, "3901:TSE")
        self.assertEqual(rows[0].earnings_date, "2026-02-13")
        self.assertEqual(rows[0].source, "株探")

    def test_sync_updates_existing_entry(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        first_source = StaticEarningsSource(
            source_name="株探",
            rows=[
                {
                    "earnings_date": "2026-02-13",
                    "earnings_time": "15:00",
                    "quarter": "3Q",
                }
            ],
        )
        second_source = StaticEarningsSource(
            source_name="株探",
            rows=[
                {
                    "earnings_date": "2026-02-13",
                    "earnings_time": "16:00",
                    "quarter": "3Q",
                }
            ],
        )

        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=first_source,
            repository=repo,
            fetched_at="2026-02-12T00:00:00+00:00",
        )
        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=second_source,
            repository=repo,
            fetched_at="2026-02-12T01:00:00+00:00",
        )

        rows = repo.list_by_ticker("3901:TSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].earnings_time, "16:00")
        self.assertEqual(rows[0].fetched_at, "2026-02-12T01:00:00+00:00")

    def test_sync_replaces_stale_rows_for_ticker(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        first_source = StaticEarningsSource(
            source_name="株探",
            rows=[
                {
                    "earnings_date": "2026-02-13",
                    "quarter": "3Q",
                }
            ],
        )
        second_source = StaticEarningsSource(
            source_name="株探",
            rows=[
                {
                    "earnings_date": "2026-02-20",
                    "quarter": "3Q",
                }
            ],
        )

        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=first_source,
            repository=repo,
            fetched_at="2026-02-12T00:00:00+00:00",
        )
        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=second_source,
            repository=repo,
            fetched_at="2026-02-12T01:00:00+00:00",
        )

        rows = repo.list_by_ticker("3901:TSE")
        self.assertEqual([(row.earnings_date, row.quarter) for row in rows], [("2026-02-20", "3Q")])

    def test_sync_clears_rows_when_source_returns_empty(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        first_source = StaticEarningsSource(
            source_name="株探",
            rows=[{"earnings_date": "2026-02-13", "quarter": "3Q"}],
        )
        empty_source = StaticEarningsSource(source_name="株探", rows=[])

        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=first_source,
            repository=repo,
            fetched_at="2026-02-12T00:00:00+00:00",
        )
        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=empty_source,
            repository=repo,
            fetched_at="2026-02-12T01:00:00+00:00",
        )

        self.assertEqual(repo.list_by_ticker("3901:TSE"), [])

    def test_sync_allows_date_only_row(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        source = StaticEarningsSource(
            source_name="株探",
            rows=[{"earnings_date": "2026-02-20"}],
        )

        sync_earnings_calendar_for_ticker(
            ticker="3901:TSE",
            source=source,
            repository=repo,
            fetched_at="2026-02-12T00:00:00+00:00",
        )

        rows = repo.list_by_ticker("3901:TSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].earnings_date, "2026-02-20")
        self.assertIsNone(rows[0].earnings_time)
        self.assertIsNone(rows[0].quarter)
        self.assertEqual(rows[0].source, "株探")
        self.assertEqual(rows[0].fetched_at, "2026-02-12T00:00:00+00:00")

    def test_list_all_sorted_by_date_ticker_quarter(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        repo.upsert(
            EarningsCalendarEntry(
                ticker="3902:TSE",
                earnings_date="2026-02-14",
                earnings_time=None,
                quarter=None,
                source=None,
                fetched_at=None,
            )
        )
        repo.upsert(
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-13",
                earnings_time=None,
                quarter="2Q",
                source=None,
                fetched_at=None,
            )
        )
        repo.upsert(
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-13",
                earnings_time=None,
                quarter="1Q",
                source=None,
                fetched_at=None,
            )
        )

        rows = repo.list_all()
        self.assertEqual(
            [(row.earnings_date, row.ticker, row.quarter) for row in rows],
            [
                ("2026-02-13", "3901:TSE", "1Q"),
                ("2026-02-13", "3901:TSE", "2Q"),
                ("2026-02-14", "3902:TSE", None),
            ],
        )

    def test_sync_raises_visible_error_when_fetch_fails(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        source = FailingEarningsSource()

        with self.assertLogs("kabu_per_bot.earnings", level="ERROR") as logs:
            with self.assertRaises(EarningsCalendarSyncError):
                sync_earnings_calendar_for_ticker(
                    ticker="3901:TSE",
                    source=source,
                    repository=repo,
                )
        self.assertIn("決算カレンダー取得失敗", logs.output[0])

    def test_sync_raises_visible_error_when_fetch_payload_is_invalid(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        source = InvalidPayloadEarningsSource()

        with self.assertLogs("kabu_per_bot.earnings", level="ERROR") as logs:
            with self.assertRaises(EarningsCalendarSyncError):
                sync_earnings_calendar_for_ticker(
                    ticker="3901:TSE",
                    source=source,
                    repository=repo,
                )
        self.assertIn("決算カレンダー取得結果不正", logs.output[0])

    def test_sync_raises_visible_error_when_row_is_invalid(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        source = StaticEarningsSource(source_name="株探", rows=[{}])

        with self.assertLogs("kabu_per_bot.earnings", level="ERROR") as logs:
            with self.assertRaises(EarningsCalendarSyncError):
                sync_earnings_calendar_for_ticker(
                    ticker="3901:TSE",
                    source=source,
                    repository=repo,
                    fetched_at="2026-02-12T00:00:00+00:00",
                )
        self.assertIn("決算カレンダー変換失敗", logs.output[0])


if __name__ == "__main__":
    unittest.main()
