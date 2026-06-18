from __future__ import annotations

import unittest

from aroll_v21.writeback.speed_resolver import SpeedResolutionError, SpeedResolver


def _segment(**extra):
    row = {
        "id": "seg_1",
        "material_id": "video_1",
        "source_timerange": {"start": 0, "duration": 1_200_000},
        "target_timerange": {"start": 0, "duration": 1_000_000},
    }
    row.update(extra)
    return row


class ArollV21V32SpeedResolverContractTests(unittest.TestCase):
    def test_speed_resolver_segment_speed_1_2(self) -> None:
        result = SpeedResolver().resolve(_segment(speed=1.2))

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "segment.speed")
        self.assertTrue(result.speed_safe)

    def test_speed_resolver_extra_speed_1_2(self) -> None:
        result = SpeedResolver().resolve(_segment(extra={"speed_ratio": "1.2"}))

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "segment.extra.speed_ratio")

    def test_speed_resolver_materials_speeds_1_2(self) -> None:
        draft_data = {"materials": {"speeds": [{"id": "speed_1", "speed": 1.2}]}}
        result = SpeedResolver().resolve(_segment(referenced_materials=[{"id": "speed_1"}]), draft_data)

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "materials.speeds.speed")

    def test_speed_resolver_referenced_speed_material_1_2(self) -> None:
        draft_data = {"materials": {"speed": [{"id": "speed_1", "speed_ratio": 1.2}]}}
        result = SpeedResolver().resolve(_segment(references=["speed_1"]), draft_data)

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "materials.speed.speed_ratio")

    def test_speed_resolver_materials_speeds_via_extra_material_refs_1_2(self) -> None:
        draft_data = {"materials": {"speeds": [{"id": "speed_2", "speed": 1.2}]}}
        result = SpeedResolver(draft_data).resolve(_segment(extra_material_refs=[{"id": "speed_2"}]))

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "materials.speeds.speed")
        self.assertEqual(result.report["extra_material_refs_scanned"], 1)
        self.assertEqual(result.report["speed_material_ref_count"], 1)

    def test_speed_resolver_material_video_speed_1_2(self) -> None:
        draft_data = {"materials": {"videos": [{"id": "video_1", "speed_ratio": 1.2}]}}
        result = SpeedResolver().resolve(_segment(), draft_data)

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "material.speed_ratio")

    def test_speed_resolver_ratio_infers_1_2_when_safe(self) -> None:
        result = SpeedResolver().resolve(_segment())

        self.assertEqual(result.speed, 1.2)
        self.assertEqual(result.speed_source, "source_target_ratio")

    def test_curve_speed_fail_closed(self) -> None:
        with self.assertRaises(SpeedResolutionError) as caught:
            SpeedResolver().resolve(_segment(curve_speed={"points": [1.0, 1.2]}))

        self.assertEqual(caught.exception.code, "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")
        self.assertEqual(caught.exception.context["reason"], "curve_speed_detected")

    def test_reverse_speed_fail_closed(self) -> None:
        with self.assertRaises(SpeedResolutionError) as caught:
            SpeedResolver().resolve(_segment(reverse=True))

        self.assertEqual(caught.exception.code, "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")
        self.assertEqual(caught.exception.context["reason"], "reverse_speed_detected")

    def test_unparseable_speed_fail_closed_not_silent_1_0(self) -> None:
        with self.assertRaises(SpeedResolutionError) as caught:
            SpeedResolver().resolve(_segment(speed="not-a-speed"))

        self.assertEqual(caught.exception.code, "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")
        self.assertEqual(caught.exception.context["reason"], "unparseable_speed")

    def test_speed_resolver_unparseable_speed_ref_fail_closed(self) -> None:
        draft_data = {"materials": {"speeds": [{"id": "speed_bad", "speed": "fast"}]}}

        with self.assertRaises(SpeedResolutionError) as caught:
            SpeedResolver(draft_data).resolve(_segment(extra_material_refs=["speed_bad"]))

        self.assertEqual(caught.exception.code, "V21_WRITEBACK_SPEED_UNPARSEABLE")
        self.assertEqual(caught.exception.context["reason"], "unparseable_speed")

    def test_speed_resolver_does_not_default_to_1_0_when_speed_ref_unreadable(self) -> None:
        with self.assertRaises(SpeedResolutionError) as caught:
            SpeedResolver({"materials": {"speeds": []}}).resolve(
                _segment(
                    extra_material_refs=["missing_speed"],
                    source_timerange={"start": 0, "duration": 1_000_000},
                    target_timerange={"start": 0, "duration": 1_000_000},
                )
            )

        self.assertEqual(caught.exception.code, "V21_WRITEBACK_SPEED_UNPARSEABLE")
        self.assertEqual(caught.exception.context["reason"], "speed_ref_unresolved")


if __name__ == "__main__":
    unittest.main()
