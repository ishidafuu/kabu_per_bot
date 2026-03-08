from __future__ import annotations

import unittest

from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType


class TechnicalProfileTest(unittest.TestCase):
    def test_round_trip_document(self) -> None:
        profile = TechnicalProfile(
            profile_id="system_large_core",
            profile_type=TechnicalProfileType.SYSTEM,
            profile_key="large_core",
            name="大型・主力",
            description="200日線重視",
            base_profile_key="large_core",
            priority_order=2,
            manual_assign_recommended=False,
            auto_assign={"all": [{"market_cap_gte": 1}]},
            thresholds={"volume_spike": 1.6},
            weights={"long_term": 40},
            flags={"use_ma200_weight": True},
            strong_alerts=("cross_down_ma200",),
            weak_alerts=("cross_up_ma200",),
            is_active=True,
            created_at="2026-03-09T00:00:00+00:00",
            updated_at="2026-03-09T00:00:00+00:00",
        )

        restored = TechnicalProfile.from_document(profile.to_document())

        self.assertEqual(restored.profile_id, "system_large_core")
        self.assertEqual(restored.profile_type, TechnicalProfileType.SYSTEM)
        self.assertEqual(restored.thresholds["volume_spike"], 1.6)
        self.assertEqual(restored.flags["use_ma200_weight"], True)
        self.assertEqual(restored.strong_alerts, ("cross_down_ma200",))

    def test_profile_requires_basic_fields(self) -> None:
        with self.assertRaises(ValueError):
            TechnicalProfile(
                profile_id="custom_x",
                profile_type=TechnicalProfileType.CUSTOM,
                profile_key="",
                name="X",
                description="Y",
            )


if __name__ == "__main__":
    unittest.main()
