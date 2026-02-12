from __future__ import annotations

from kabu_per_bot.settings import load_settings


def main() -> int:
    settings = load_settings()
    print("kabu_per_bot started")
    print(
        "config: "
        f"timezone={settings.timezone}, "
        f"windows={settings.window_1w_days}/{settings.window_3m_days}/{settings.window_1y_days}, "
        f"cooldown_hours={settings.cooldown_hours}, "
        f"firestore_project_id={settings.firestore_project_id or '(unset)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
