from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_technical_profiles_repository import FirestoreTechnicalProfilesRepository
from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType


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
        del merge
        self.db[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        if self.path not in self.db:
            return FakeSnapshot(exists=False, data=None)
        return FakeSnapshot(exists=True, data=dict(self.db[self.path]))

    def delete(self) -> None:
        self.db.pop(self.path, None)


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


class FirestoreTechnicalProfilesRepositoryTest(unittest.TestCase):
    def test_crud(self) -> None:
        repo = FirestoreTechnicalProfilesRepository(FakeFirestoreClient())
        profile = TechnicalProfile(
            profile_id="system_low_liquidity",
            profile_type=TechnicalProfileType.SYSTEM,
            profile_key="low_liquidity",
            name="低流動性",
            description="低流動性",
            priority_order=1,
            thresholds={"volume_spike": 3.0},
            weights={"liquidity": 30},
            flags={"suppress_minor_alerts": True},
            strong_alerts=("breakdown_ma75",),
            weak_alerts=("cross_up_ma25",),
            created_at="2026-03-09T00:00:00+00:00",
            updated_at="2026-03-09T00:00:00+00:00",
        )

        repo.upsert(profile)
        found = repo.get("system_low_liquidity")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.thresholds["volume_spike"], 3.0)
        self.assertEqual(repo.list_all()[0].profile_id, "system_low_liquidity")
        self.assertTrue(repo.delete("system_low_liquidity"))
        self.assertFalse(repo.delete("system_low_liquidity"))

    def test_list_all_sorts_system_before_custom(self) -> None:
        repo = FirestoreTechnicalProfilesRepository(FakeFirestoreClient())
        repo.upsert(
            TechnicalProfile(
                profile_id="custom_growth_fast",
                profile_type=TechnicalProfileType.CUSTOM,
                profile_key="growth_fast",
                name="成長強気",
                description="custom",
            )
        )
        repo.upsert(
            TechnicalProfile(
                profile_id="system_large_core",
                profile_type=TechnicalProfileType.SYSTEM,
                profile_key="large_core",
                name="大型・主力",
                description="system",
                priority_order=2,
            )
        )

        rows = repo.list_all()
        self.assertEqual(rows[0].profile_type, TechnicalProfileType.SYSTEM)
        self.assertEqual(rows[1].profile_type, TechnicalProfileType.CUSTOM)


if __name__ == "__main__":
    unittest.main()
