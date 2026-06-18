from __future__ import annotations

import unittest

from aroll_v21.writeback.effect_policy import EffectTrackPolicy


class ArollV21V32EffectPolicyContractTests(unittest.TestCase):
    def test_embedded_beauty_effect_preserved_by_template_deepcopy(self) -> None:
        draft_data = {
            "tracks": [
                {
                    "id": "video_track",
                    "type": "video",
                    "segments": [{"id": "v1", "beauty": {"smooth": 0.5}}],
                }
            ]
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertTrue(result.safe)
        self.assertTrue(result.report["segment_embedded_effects_preserved"])

    def test_effect_policy_detects_extra_material_refs_effects(self) -> None:
        draft_data = {
            "materials": {"effects": [{"id": "effect_1", "type": "figure", "sub_type": "auto_beauty"}]},
            "tracks": [
                {
                    "id": "video_track",
                    "type": "video",
                    "segments": [{"id": "v1", "extra_material_refs": ["effect_1"]}],
                }
            ],
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertTrue(result.safe)
        self.assertTrue(result.report["segment_embedded_effects_preserved"])
        self.assertEqual(result.report["effect_material_ref_count"], 1)

    def test_effect_policy_detects_video_material_beauty_face_preset_infos(self) -> None:
        draft_data = {
            "materials": {"videos": [{"id": "video_1", "beauty_face_preset_infos": [{"name": "smooth"}]}]},
            "tracks": [
                {
                    "id": "video_track",
                    "type": "video",
                    "segments": [{"id": "v1", "material_id": "video_1"}],
                }
            ],
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertTrue(result.safe)
        self.assertTrue(result.report["segment_embedded_effects_preserved"])
        self.assertEqual(result.report["beauty_video_material_count"], 1)

    def test_effect_policy_detects_realtime_denoises(self) -> None:
        draft_data = {
            "materials": {"realtime_denoises": [{"id": "denoise_1"}]},
            "tracks": [{"id": "video_track", "type": "video", "segments": [{"id": "v1"}]}],
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertTrue(result.safe)
        self.assertTrue(result.report["segment_embedded_effects_preserved"])
        self.assertEqual(result.report["realtime_denoise_count"], 1)

    def test_global_filter_track_remapped_to_final_timeline(self) -> None:
        draft_data = {
            "tracks": [
                {
                    "id": "filter_track",
                    "type": "filter",
                    "segments": [{"id": "f1", "target_timerange": {"start": 0, "duration": 1_000_000}}],
                }
            ]
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertTrue(result.safe)
        self.assertTrue(result.report["global_filter_effect_remapped"])

    def test_complex_filter_track_blocks_write_by_default(self) -> None:
        draft_data = {
            "tracks": [
                {
                    "id": "filter_track",
                    "type": "filter",
                    "segments": [{"id": "f1", "target_timerange": {"start": 200_000, "duration": 100_000}}],
                }
            ]
        }

        result = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)

        self.assertFalse(result.safe)
        self.assertEqual(result.blocker_code, "V21_WRITEBACK_UNSUPPORTED_COMPLEX_EFFECT_TRACK")
        self.assertEqual(result.report["unsupported_effect_track_count"], 1)

    def test_allow_preserve_unsupported_effect_track_requires_explicit_flag(self) -> None:
        draft_data = {
            "tracks": [
                {
                    "id": "filter_track",
                    "type": "effect",
                    "segments": [{"id": "fx1", "target_timerange": {"start": 200_000, "duration": 100_000}}],
                }
            ]
        }

        blocked = EffectTrackPolicy().inspect(draft_data, final_duration_us=1_000_000)
        allowed = EffectTrackPolicy().inspect(
            draft_data,
            final_duration_us=1_000_000,
            allow_preserve_unsupported_effect_tracks=True,
        )

        self.assertFalse(blocked.safe)
        self.assertTrue(allowed.safe)
        self.assertTrue(allowed.report["allow_preserve_unsupported_effect_tracks"])


if __name__ == "__main__":
    unittest.main()
