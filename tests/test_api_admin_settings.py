from __future__ import annotations

from dataclasses import dataclass
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import UnauthorizedError
from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.settings import AppSettings


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, object]:
        if token == "admin-token":
            return {"uid": "admin-user", "admin": True}
        if token == "user-token":
            return {"uid": "normal-user"}
        raise UnauthorizedError("認証に失敗しました。")


@dataclass
class FakeGlobalSettingsRepository:
    settings: GlobalRuntimeSettings = GlobalRuntimeSettings()

    def get_global_settings(self) -> GlobalRuntimeSettings:
        return self.settings

    def upsert_global_settings(
        self,
        *,
        cooldown_hours: int | None = None,
        immediate_schedule: ImmediateSchedule | None = None,
        updated_at: str,
        updated_by: str | None,
    ) -> None:
        next_cooldown = self.settings.cooldown_hours if cooldown_hours is None else cooldown_hours
        next_schedule = self.settings.immediate_schedule if immediate_schedule is None else immediate_schedule
        self.settings = GlobalRuntimeSettings(
            cooldown_hours=next_cooldown,
            immediate_schedule=next_schedule,
            updated_at=updated_at,
            updated_by=updated_by,
        )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app_settings(*, cooldown_hours: int) -> AppSettings:
    return AppSettings(
        app_env="test",
        timezone="Asia/Tokyo",
        window_1w_days=5,
        window_3m_days=63,
        window_1y_days=252,
        cooldown_hours=cooldown_hours,
        firestore_project_id="demo-project",
        ai_notifications_enabled=False,
        x_api_bearer_token="",
    )


class AdminSettingsApiTest(unittest.TestCase):
    def test_get_global_settings_requires_admin_role(self) -> None:
        app = create_app(
            global_settings_repository=FakeGlobalSettingsRepository(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.get("/api/v1/admin/settings/global", headers=_auth_header("user-token"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_get_global_settings_returns_env_default_when_not_overridden(self) -> None:
        app = create_app(
            global_settings_repository=FakeGlobalSettingsRepository(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        with patch(
            "kabu_per_bot.api.routes.admin_settings.load_settings",
            return_value=_app_settings(cooldown_hours=2),
        ):
            response = client.get("/api/v1/admin/settings/global", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cooldown_hours"], 2)
        self.assertTrue(body["immediate_schedule"]["enabled"])
        self.assertEqual(body["source"], "env_default")
        self.assertIsNone(body["updated_at"])

    def test_get_global_settings_returns_firestore_override(self) -> None:
        app = create_app(
            global_settings_repository=FakeGlobalSettingsRepository(
                settings=GlobalRuntimeSettings(
                    cooldown_hours=4,
                    immediate_schedule=ImmediateSchedule(
                        enabled=False,
                        timezone="Asia/Tokyo",
                        open_window_start="09:30",
                        open_window_end="10:30",
                        open_window_interval_min=20,
                        close_window_start="14:00",
                        close_window_end="15:00",
                        close_window_interval_min=20,
                    ),
                    updated_at="2026-02-18T12:00:00+00:00",
                    updated_by="admin-user",
                )
            ),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        with patch(
            "kabu_per_bot.api.routes.admin_settings.load_settings",
            return_value=_app_settings(cooldown_hours=2),
        ):
            response = client.get("/api/v1/admin/settings/global", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cooldown_hours"], 4)
        self.assertFalse(body["immediate_schedule"]["enabled"])
        self.assertEqual(body["immediate_schedule"]["open_window_start"], "09:30")
        self.assertEqual(body["source"], "firestore")
        self.assertEqual(body["updated_by"], "admin-user")

    def test_patch_global_settings_updates_cooldown_hours(self) -> None:
        repository = FakeGlobalSettingsRepository()
        app = create_app(
            global_settings_repository=repository,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        with patch(
            "kabu_per_bot.api.routes.admin_settings.load_settings",
            return_value=_app_settings(cooldown_hours=2),
        ):
            response = client.patch(
                "/api/v1/admin/settings/global",
                headers=_auth_header("admin-token"),
                json={"cooldown_hours": 6},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cooldown_hours"], 6)
        self.assertEqual(body["source"], "firestore")
        self.assertEqual(body["updated_by"], "admin-user")
        self.assertEqual(repository.settings.cooldown_hours, 6)

    def test_patch_global_settings_updates_immediate_schedule(self) -> None:
        repository = FakeGlobalSettingsRepository()
        app = create_app(
            global_settings_repository=repository,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        with patch(
            "kabu_per_bot.api.routes.admin_settings.load_settings",
            return_value=_app_settings(cooldown_hours=2),
        ):
            response = client.patch(
                "/api/v1/admin/settings/global",
                headers=_auth_header("admin-token"),
                json={
                    "immediate_schedule": {
                        "enabled": False,
                        "open_window_start": "09:15",
                        "open_window_end": "10:15",
                        "open_window_interval_min": 30,
                        "close_window_start": "14:45",
                        "close_window_end": "15:45",
                        "close_window_interval_min": 15,
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cooldown_hours"], 2)
        self.assertFalse(body["immediate_schedule"]["enabled"])
        self.assertEqual(body["immediate_schedule"]["open_window_interval_min"], 30)
        self.assertIsNotNone(repository.settings.immediate_schedule)
        self.assertFalse(repository.settings.immediate_schedule.enabled)

    def test_patch_global_settings_rejects_window_overlap(self) -> None:
        repository = FakeGlobalSettingsRepository()
        app = create_app(
            global_settings_repository=repository,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.patch(
            "/api/v1/admin/settings/global",
            headers=_auth_header("admin-token"),
            json={
                "immediate_schedule": {
                    "enabled": True,
                    "open_window_start": "09:00",
                    "open_window_end": "10:00",
                    "open_window_interval_min": 15,
                    "close_window_start": "09:30",
                    "close_window_end": "10:30",
                    "close_window_interval_min": 10,
                }
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
