from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.intelligence import IntelEvent, IntelKind
from kabu_per_bot.storage.firestore_intel_seen_repository import FirestoreIntelSeenRepository


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
        if merge and self.path in self.db:
            merged = dict(self.db[self.path])
            merged.update(data)
            self.db[self.path] = merged
            return
        self.db[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        if self.path not in self.db:
            return FakeSnapshot(exists=False, data=None)
        return FakeSnapshot(exists=True, data=dict(self.db[self.path]))


@dataclass
class FakeCollectionRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def document(self, document_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(path=f"{self.path}/{document_id}", db=self.db)

    def where(self, field: str, op: str, value: str) -> "FakeQuery":
        return FakeQuery(path=self.path, db=self.db, filters=[(field, op, value)])

    def stream(self):
        prefix = f"{self.path}/"
        for key, value in self.db.items():
            if not key.startswith(prefix):
                continue
            yield FakeSnapshot(exists=True, data=dict(value))


@dataclass
class FakeQuery:
    path: str
    db: dict[str, dict] = field(default_factory=dict)
    filters: list[tuple[str, str, str]] = field(default_factory=list)
    _limit: int | None = None

    def where(self, field: str, op: str, value: str) -> "FakeQuery":
        return FakeQuery(
            path=self.path,
            db=self.db,
            filters=[*self.filters, (field, op, value)],
            _limit=self._limit,
        )

    def limit(self, value: int) -> "FakeQuery":
        return FakeQuery(path=self.path, db=self.db, filters=self.filters, _limit=value)

    def stream(self):
        prefix = f"{self.path}/"
        rows: list[dict] = []
        for key, value in self.db.items():
            if not key.startswith(prefix):
                continue
            rows.append(dict(value))

        for field, op, expected in self.filters:
            if op != "==":
                continue
            rows = [row for row in rows if str(row.get(field, "")) == expected]

        if self._limit is not None:
            rows = rows[: self._limit]

        for row in rows:
            yield FakeSnapshot(exists=True, data=row)


@dataclass
class FakeBrokenQuery(FakeQuery):
    def stream(self):
        raise RuntimeError("The query requires an index.")


@dataclass
class FakeBrokenCollectionRef(FakeCollectionRef):
    def where(self, field: str, op: str, value: str) -> "FakeQuery":
        return FakeBrokenQuery(path=self.path, db=self.db, filters=[(field, op, value)])


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


@dataclass
class FakeBrokenQueryFirestoreClient(FakeFirestoreClient):
    def collection(self, name: str) -> FakeCollectionRef:
        return FakeBrokenCollectionRef(path=name, db=self.db)


class FirestoreIntelSeenRepositoryTest(unittest.TestCase):
    def test_mark_and_exists(self) -> None:
        repo = FirestoreIntelSeenRepository(FakeFirestoreClient())
        event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料",
            url="https://example.com/ir/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開",
        )
        self.assertFalse(repo.exists(event.fingerprint))
        repo.mark_seen(event, seen_at="2026-02-15T00:10:00+09:00")
        self.assertTrue(repo.exists(event.fingerprint))
        self.assertTrue(repo.has_any_for_ticker("3901:TSE"))
        self.assertFalse(repo.has_any_for_ticker("6501:TSE"))

    def test_has_any_for_ticker_and_kind(self) -> None:
        repo = FirestoreIntelSeenRepository(FakeFirestoreClient())
        sns_event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.SNS,
            title="@official",
            url="https://x.com/official/status/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="公式",
            content="投稿",
        )
        ir_event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料",
            url="https://example.com/ir/2",
            published_at="2026-02-16T00:00:00+09:00",
            source_label="IRサイト",
            content="本文",
        )

        repo.mark_seen(sns_event, seen_at="2026-02-15T00:10:00+09:00")
        self.assertTrue(repo.has_any_for_ticker_and_kind("3901:TSE", IntelKind.SNS))
        self.assertFalse(repo.has_any_for_ticker_and_kind("3901:TSE", IntelKind.IR))

        repo.mark_seen(ir_event, seen_at="2026-02-16T00:10:00+09:00")
        self.assertTrue(repo.has_any_for_ticker_and_kind("3901:TSE", IntelKind.IR))

    def test_has_any_for_ticker_and_kind_fallback_when_query_requires_index(self) -> None:
        repo = FirestoreIntelSeenRepository(FakeBrokenQueryFirestoreClient())
        event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料",
            url="https://example.com/ir/2",
            published_at="2026-02-16T00:00:00+09:00",
            source_label="IRサイト",
            content="本文",
        )

        repo.mark_seen(event, seen_at="2026-02-16T00:10:00+09:00")
        self.assertTrue(repo.has_any_for_ticker_and_kind("3901:TSE", IntelKind.IR))
        self.assertFalse(repo.has_any_for_ticker_and_kind("3901:TSE", IntelKind.SNS))


if __name__ == "__main__":
    unittest.main()
