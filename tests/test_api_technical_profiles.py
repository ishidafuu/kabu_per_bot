from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from fastapi.testclient import TestClient

from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import UnauthorizedError
from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, object]:
        if token == "admin-token":
            return {"uid": "admin-user", "admin": True}
        if token == "user-token":
            return {"uid": "normal-user"}
        raise UnauthorizedError("認証に失敗しました。")


@dataclass
class InMemoryTechnicalProfilesRepository:
    docs: dict[str, TechnicalProfile] = field(default_factory=dict)

    def get(self, profile_id: str) -> TechnicalProfile | None:
        return self.docs.get(profile_id)

    def list_all(self, *, include_inactive: bool = True) -> list[TechnicalProfile]:
        values = list(self.docs.values())
        if not include_inactive:
            values = [value for value in values if value.is_active]
        values.sort(
            key=lambda row: (
                0 if row.profile_type == TechnicalProfileType.SYSTEM else 1,
                row.priority_order if row.priority_order is not None else 9999,
                row.name,
            )
        )
        return values

    def upsert(self, profile: TechnicalProfile) -> None:
        self.docs[profile.profile_id] = profile

    def delete(self, profile_id: str) -> bool:
        return self.docs.pop(profile_id, None) is not None


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _system_profile() -> TechnicalProfile:
    return TechnicalProfile(
        profile_id="system_large_core",
        profile_type=TechnicalProfileType.SYSTEM,
        profile_key="large_core",
        name="大型・主力",
        description="大型株向けの標準プロファイル",
        thresholds={"volume_spike": 1.6},
        weights={"long_term": 40},
        flags={"use_ma200_weight": True},
        strong_alerts=("cross_down_ma200",),
        weak_alerts=("cross_up_ma200",),
        created_at="2026-03-08T00:00:00+00:00",
        updated_at="2026-03-08T00:00:00+00:00",
    )


class TechnicalProfilesApiTest(unittest.TestCase):
    def _client(self, repository: InMemoryTechnicalProfilesRepository) -> TestClient:
        app = create_app(
            technical_profiles_repository=repository,
            token_verifier=FakeTokenVerifier(),
        )
        return TestClient(app)

    def test_requires_admin_role(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.get("/api/v1/technical-profiles", headers=_auth_header("user-token"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_list_profiles(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.get("/api/v1/technical-profiles", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["profile_key"], "large_core")

    def test_get_profile(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.get("/api/v1/technical-profiles/system_large_core", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile_type"], "SYSTEM")

    def test_create_custom_profile(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.post(
            "/api/v1/technical-profiles",
            headers=_auth_header("admin-token"),
            json={
                "profile_key": "swing_plus",
                "name": "スイング強気",
                "description": "短中期の上昇を重視するカスタム",
                "base_profile_key": "small_growth",
                "thresholds": {"volume_spike": 2.2},
                "weights": {"demand": 30},
                "flags": {"suppress_minor_alerts": False},
                "strong_alerts": ["trend_change_to_down"],
                "weak_alerts": ["turnover_spike"],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["profile_id"], "custom_swing_plus")
        self.assertEqual(body["profile_type"], "CUSTOM")
        self.assertEqual(repository.get("custom_swing_plus").thresholds["volume_spike"], 2.2)

    def test_create_rejects_duplicate_profile_key(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.post(
            "/api/v1/technical-profiles",
            headers=_auth_header("admin-token"),
            json={
                "profile_key": "large_core",
                "name": "重複",
                "description": "重複キー",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")

    def test_clone_system_profile_to_custom(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.post(
            "/api/v1/technical-profiles/system_large_core/clone",
            headers=_auth_header("admin-token"),
            json={
                "profile_key": "large_core_soft",
                "name": "大型・主力（緩め）",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["profile_type"], "CUSTOM")
        self.assertEqual(body["base_profile_key"], "large_core")
        self.assertEqual(body["thresholds"]["volume_spike"], 1.6)

    def test_update_custom_profile(self) -> None:
        custom = TechnicalProfile(
            profile_id="custom_swing_plus",
            profile_type=TechnicalProfileType.CUSTOM,
            profile_key="swing_plus",
            name="スイング強気",
            description="初期説明",
            thresholds={"volume_spike": 2.0},
            created_at="2026-03-08T00:00:00+00:00",
            updated_at="2026-03-08T00:00:00+00:00",
        )
        repository = InMemoryTechnicalProfilesRepository(
            {
                "system_large_core": _system_profile(),
                "custom_swing_plus": custom,
            }
        )
        client = self._client(repository)

        response = client.patch(
            "/api/v1/technical-profiles/custom_swing_plus",
            headers=_auth_header("admin-token"),
            json={
                "description": "更新後説明",
                "thresholds": {"volume_spike": 2.5},
                "is_active": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["description"], "更新後説明")
        self.assertEqual(body["thresholds"]["volume_spike"], 2.5)
        self.assertFalse(body["is_active"])

    def test_update_system_profile_is_rejected(self) -> None:
        repository = InMemoryTechnicalProfilesRepository({"system_large_core": _system_profile()})
        client = self._client(repository)

        response = client.patch(
            "/api/v1/technical-profiles/system_large_core",
            headers=_auth_header("admin-token"),
            json={"description": "更新"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")


if __name__ == "__main__":
    unittest.main()
