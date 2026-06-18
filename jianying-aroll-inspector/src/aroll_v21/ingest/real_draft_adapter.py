from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jy_bridge import DEFAULT_JY_DRAFTC, decrypt

from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider
from aroll_v21.ir.models import Blocker


DecryptFunc = Callable[[Path, Path, Path], None]
TEXT_WORD_TIME_TOLERANCE_US = 80_000


@dataclass(frozen=True)
class PrimaryVideoWindow:
    track_id: str
    segment_id: str
    material_id: str
    target_start_us: int
    target_end_us: int
    material_local_source_start_us: int
    material_local_source_end_us: int
    speed: float
    window_index: int
    target_duration_us: int


@dataclass(frozen=True)
class RealDraftIngestResult:
    draft_data: dict[str, Any] = field(default_factory=dict)
    word_timeline: list[dict[str, Any]] = field(default_factory=list)
    subtitles: list[dict[str, Any]] = field(default_factory=list)
    source_materials: list[dict[str, Any]] = field(default_factory=list)
    source_segments: list[dict[str, Any]] = field(default_factory=list)
    text_materials: list[dict[str, Any]] = field(default_factory=list)
    text_segments: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _timerange(row: dict[str, Any], key: str) -> dict[str, int]:
    value = row.get(key)
    if not isinstance(value, dict) and isinstance(row.get("clip"), dict):
        value = row["clip"].get(key)
    if not isinstance(value, dict):
        return {}
    start = int(value.get("start") or 0)
    duration = int(value.get("duration") or 0)
    end = int(value.get("end") or (start + duration if duration else 0))
    return {"start_us": start, "end_us": end, "duration_us": max(0, end - start)}


def _track_type(track: dict[str, Any]) -> str:
    return str(track.get("type") or track.get("track_type") or "").lower()


def _material_id(segment: dict[str, Any]) -> str:
    return str(segment.get("material_id") or segment.get("materialId") or "")


def _content_text(material: dict[str, Any]) -> str:
    for key in ("text", "recognize_text"):
        value = material.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("content", "base_content"):
        value = material.get(key)
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
        elif isinstance(value, dict):
            payload = value
        else:
            continue
        text = payload.get("text") if isinstance(payload, dict) else None
        if isinstance(text, str) and text.strip():
            return text
    return ""


class RealDraftIngestAdapter:
    """Read a user-authorized real Jianying draft into V21 input rows.

    This adapter is read-only. It may decrypt draft_content into a temporary
    file under run_dir, reads the JSON, then deletes the temporary plaintext.
    It does not write draft files, does not call encrypt, and does not invoke
    legacy orchestration or writeback modules.
    """

    def __init__(
        self,
        *,
        jy_draftc: Path | None = None,
        decrypt_func: DecryptFunc | None = None,
        word_timeline_provider: DefaultWordTimelineProvider | None = None,
    ) -> None:
        self.jy_draftc = Path(jy_draftc) if jy_draftc is not None else Path(DEFAULT_JY_DRAFTC)
        self.decrypt_func = decrypt_func or decrypt
        self.word_timeline_provider = word_timeline_provider or DefaultWordTimelineProvider()

    def load(self, draft_dir: Path, run_dir: Path, *, word_timeline_json: Path | None = None) -> RealDraftIngestResult:
        draft_dir = Path(draft_dir)
        run_dir = Path(run_dir)
        blockers: list[Blocker] = []
        metadata: dict[str, Any] = {"draft_dir": str(draft_dir), "adapter": "RealDraftIngestAdapter"}

        if not draft_dir.exists() or not draft_dir.is_dir():
            return RealDraftIngestResult(
                blockers=[
                    Blocker(
                        code="REAL_DRAFT_REQUIRED_FILE_MISSING",
                        message="disposable draft directory does not exist",
                        layer="operator",
                        context={"draft_dir": str(draft_dir)},
                    )
                ],
                metadata=metadata,
            )

        timeline = self._resolve_timeline(draft_dir)
        if isinstance(timeline, Blocker):
            return RealDraftIngestResult(blockers=[timeline], metadata=metadata)
        timeline_id, timeline_dir = timeline
        metadata["timeline_id"] = timeline_id
        metadata["timeline_dir"] = str(timeline_dir)

        draft_content_path = timeline_dir / "draft_content.json"
        template_path = timeline_dir / "template-2.tmp"
        missing = [str(path) for path in (draft_content_path, template_path) if not path.exists()]
        if missing:
            return RealDraftIngestResult(
                blockers=[
                    Blocker(
                        code="REAL_DRAFT_REQUIRED_FILE_MISSING",
                        message="required real draft timeline file is missing",
                        layer="operator",
                        context={"missing_files": missing, "timeline_dir": str(timeline_dir)},
                    )
                ],
                metadata=metadata,
            )

        data, decrypt_blocker = self._decrypt_draft_content(draft_content_path, run_dir)
        if decrypt_blocker is not None:
            return RealDraftIngestResult(blockers=[decrypt_blocker], metadata=metadata)
        if not isinstance(data, dict):
            return RealDraftIngestResult(
                blockers=[
                    Blocker(
                        code="REAL_DRAFT_SCHEMA_UNSUPPORTED",
                        message="decrypted draft_content root is not an object",
                        layer="operator",
                        context={"timeline_dir": str(timeline_dir)},
                    )
                ],
                metadata=metadata,
            )

        materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
        text_materials = [dict(row) for row in (materials.get("texts") or []) if isinstance(row, dict)]
        tracks = [dict(row) for row in (data.get("tracks") or []) if isinstance(row, dict)]
        text_segments = self._text_segments(tracks)
        source_segments = self._source_segments(tracks)
        source_materials = self._source_materials(data, source_segments)
        subtitles = self._subtitle_rows(text_segments, text_materials)
        word_result = self.word_timeline_provider.load(
            draft_data=data,
            external_path=word_timeline_json,
            text_materials=text_materials,
            text_segments=text_segments,
            source_segments=source_segments,
        )
        word_timeline, mapping_blockers, mapping_metadata = self._bind_word_rows(word_result.words, subtitles, source_segments)
        blockers.extend(word_result.blockers)
        blockers.extend(mapping_blockers)
        word_metadata = dict(word_result.metadata)
        word_metadata["native_word_mapping"] = mapping_metadata

        if not text_materials:
            blockers.append(Blocker("REAL_DRAFT_TEXT_MATERIALS_MISSING", "draft has no text materials", "ingest"))
        if not text_segments:
            blockers.append(Blocker("REAL_DRAFT_TEXT_SEGMENTS_MISSING", "draft has no text/subtitle segments", "ingest"))
        if not source_segments:
            blockers.append(Blocker("REAL_DRAFT_SOURCE_SEGMENTS_MISSING", "draft has no source media segments", "ingest"))
        if source_segments and not source_materials:
            blockers.append(Blocker("REAL_DRAFT_SOURCE_MATERIALS_MISSING", "draft source material inventory is missing", "ingest"))
        if not word_timeline:
            blockers.append(
                Blocker(
                    "REAL_DRAFT_SPEECH_TIMELINE_MISSING",
                    "real draft does not expose a usable speech timeline",
                    "ingest",
                    context={"timeline_id": timeline_id},
                )
            )

        metadata.update(
            {
                "draft_content_path": str(draft_content_path),
                "template_path": str(template_path),
                "text_material_count": len(text_materials),
                "text_segment_count": len(text_segments),
                "source_segment_count": len(source_segments),
                "source_material_count": len(source_materials),
                "subtitle_candidate_count": len(subtitles),
                "word_timeline_count": len(word_timeline),
                "word_timeline_provider": word_metadata,
                "speech_timeline_provider": word_metadata.get("speech_timeline_provider") or "",
                "speech_timeline_granularity": word_metadata.get("speech_timeline_granularity") or "",
                "speech_timeline_precision": word_metadata.get("precision") or "",
                "speech_timeline_can_cut_inside_caption": bool(word_metadata.get("can_cut_inside_caption")),
                "native_word_mapping": mapping_metadata,
                "decrypted_plaintext_persisted": False,
            }
        )
        return RealDraftIngestResult(
            draft_data=data,
            word_timeline=word_timeline,
            subtitles=subtitles,
            source_materials=source_materials,
            source_segments=source_segments,
            text_materials=text_materials,
            text_segments=text_segments,
            blockers=blockers,
            metadata=metadata,
        )

    def _resolve_timeline(self, draft_dir: Path) -> tuple[str, Path] | Blocker:
        layout_path = draft_dir / "timeline_layout.json"
        timelines_dir = draft_dir / "Timelines"
        if not layout_path.exists():
            return Blocker(
                code="REAL_DRAFT_REQUIRED_FILE_MISSING",
                message="timeline_layout.json is required to resolve active timeline",
                layer="operator",
                context={"missing_file": str(layout_path)},
            )
        if not timelines_dir.exists():
            return Blocker(
                code="REAL_DRAFT_REQUIRED_FILE_MISSING",
                message="Timelines directory is required",
                layer="operator",
                context={"missing_file": str(timelines_dir)},
            )
        try:
            layout = _read_json(layout_path)
        except Exception as exc:
            return Blocker(
                code="REAL_DRAFT_SCHEMA_UNSUPPORTED",
                message="timeline_layout.json could not be parsed",
                layer="operator",
                context={"file": str(layout_path), "error": str(exc)},
            )
        timeline_id = str((layout or {}).get("activeTimeline") or "").strip()
        if not timeline_id:
            candidates = [path for path in timelines_dir.iterdir() if path.is_dir()]
            if len(candidates) == 1:
                timeline_id = candidates[0].name
        if not timeline_id:
            return Blocker(
                code="REAL_DRAFT_SCHEMA_UNSUPPORTED",
                message="active timeline id is missing",
                layer="operator",
                context={"file": str(layout_path)},
            )
        timeline_dir = timelines_dir / timeline_id
        if not timeline_dir.exists():
            return Blocker(
                code="REAL_DRAFT_REQUIRED_FILE_MISSING",
                message="active timeline directory is missing",
                layer="operator",
                context={"timeline_id": timeline_id, "timeline_dir": str(timeline_dir)},
            )
        return timeline_id, timeline_dir

    def _decrypt_draft_content(self, draft_content_path: Path, run_dir: Path) -> tuple[dict[str, Any] | None, Blocker | None]:
        tmp_dir = run_dir / ".v21_real_ingest_tmp"
        plain_path = tmp_dir / "draft_content.dec.json"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=True)
            self.decrypt_func(self.jy_draftc, draft_content_path, plain_path)
            payload = _read_json(plain_path)
            return payload, None
        except Exception as exc:
            return None, Blocker(
                code="REAL_DRAFT_DECRYPT_FAILED",
                message="real draft_content decrypt/read failed",
                layer="operator",
                context={"draft_content_path": str(draft_content_path), "error": str(exc)},
            )
        finally:
            try:
                plain_path.unlink()
            except FileNotFoundError:
                pass
            try:
                shutil.rmtree(tmp_dir)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _text_segments(self, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for track in tracks:
            track_type = _track_type(track)
            if "text" not in track_type and "subtitle" not in track_type:
                continue
            for segment in track.get("segments") or []:
                if isinstance(segment, dict):
                    row = dict(segment)
                    row["track_id"] = str(track.get("id") or "")
                    row["track_type"] = track_type
                    rows.append(row)
        return rows

    def _source_segments(self, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for track in tracks:
            track_type = _track_type(track)
            if "video" not in track_type and "audio" not in track_type:
                continue
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                row = dict(segment)
                row["track_id"] = str(track.get("id") or "")
                row["track_type"] = track_type
                source_time = _timerange(row, "source_timerange")
                if source_time:
                    row.setdefault("material_local_source_start_us", source_time["start_us"])
                    row.setdefault("material_local_source_end_us", source_time["end_us"])
                    row.setdefault("duration_us", source_time["duration_us"])
                target_time = _timerange(row, "target_timerange")
                if target_time:
                    row.setdefault("target_start_us", target_time["start_us"])
                    row.setdefault("target_end_us", target_time["end_us"])
                    row.setdefault("target_duration_us", target_time["duration_us"])
                    if "video" in track_type:
                        row["canonical_source_start_us"] = target_time["start_us"]
                        row["canonical_source_end_us"] = target_time["end_us"]
                        row["source_start_us"] = target_time["start_us"]
                        row["source_end_us"] = target_time["end_us"]
                elif source_time:
                    row.setdefault("source_start_us", source_time["start_us"])
                    row.setdefault("source_end_us", source_time["end_us"])
                row.setdefault("material_id", _material_id(row))
                rows.append(row)
        return rows

    def _source_materials(self, data: dict[str, Any], source_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
        rows: list[dict[str, Any]] = []
        for key, material_type in (("videos", "video"), ("audios", "audio")):
            for material in materials.get(key) or []:
                if not isinstance(material, dict):
                    continue
                material_id = str(material.get("id") or material.get("material_id") or "")
                if not material_id:
                    continue
                rows.append(
                    {
                        "source_material_id": material_id,
                        "path": str(material.get("path") or material.get("local_material_id") or material.get("name") or ""),
                        "duration_us": int(material.get("duration_us") or material.get("duration") or 0),
                        "type": material_type,
                        "metadata": {k: v for k, v in material.items() if k not in {"id", "path", "duration_us", "duration"}},
                    }
                )
        if rows:
            return rows
        seen: set[str] = set()
        for segment in source_segments:
            material_id = str(segment.get("material_id") or segment.get("source_material_id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            rows.append(
                {
                    "source_material_id": material_id,
                    "path": str(segment.get("path") or ""),
                    "duration_us": int(segment.get("duration_us") or max(0, _timerange(segment, "source_timerange").get("duration_us", 0))),
                    "type": "video" if "video" in str(segment.get("track_type") or "").lower() else "unknown",
                    "metadata": {"inventory_source": "source_segment"},
                }
            )
        return rows

    def _subtitle_rows(self, text_segments: list[dict[str, Any]], text_materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        material_by_id = {str(row.get("id") or ""): row for row in text_materials}
        rows: list[dict[str, Any]] = []
        for index, segment in enumerate(text_segments, start=1):
            material_id = _material_id(segment)
            material = material_by_id.get(material_id) or {}
            text = _content_text(material)
            target_time = _timerange(segment, "target_timerange")
            row = {
                "subtitle_uid": str(segment.get("id") or f"real_subtitle_{index:06d}"),
                "subtitle_index": index,
                "text": text,
                "subtitle_text": text,
                "text_material_id": material_id,
                "segment": segment,
                "material": material,
            }
            if target_time:
                row["start_us"] = target_time["start_us"]
                row["end_us"] = target_time["end_us"]
                row["duration_us"] = target_time["duration_us"]
            rows.append(row)
        return rows

    def _bind_word_rows(
        self,
        words: list[dict[str, Any]],
        subtitles: list[dict[str, Any]],
        source_segments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[Blocker], dict[str, Any]]:
        subtitle_by_material_id = {str(row.get("text_material_id") or ""): row for row in subtitles if row.get("text_material_id")}
        subtitle_by_uid = {str(row.get("subtitle_uid") or ""): row for row in subtitles if row.get("subtitle_uid")}
        subtitle_by_index = {int(row.get("subtitle_index") or 0): row for row in subtitles if row.get("subtitle_index") is not None}
        primary_windows, primary_window_blockers = self._primary_video_windows(source_segments)
        bound: list[dict[str, Any]] = []
        blockers: list[Blocker] = list(primary_window_blockers)
        mapped_to_text_segment_count = 0
        mapped_to_source_segment_count = 0
        relative_time_count = 0
        source_time_out_of_segment_count = 0
        time_clamped_within_tolerance_count = 0
        time_basis_counts = {
            "relative_to_text_segment_count": 0,
            "absolute_timeline_count": 0,
            "unresolved_count": 0,
        }
        sample_mapped_words: list[dict[str, Any]] = []
        for index, word in enumerate(words, start=1):
            row = dict(word)
            material_id = str(row.get("text_material_id") or row.get("text_material") or "")
            subtitle = subtitle_by_material_id.get(material_id) if material_id else None
            if subtitle is None and row.get("subtitle_uid"):
                subtitle = subtitle_by_uid.get(str(row.get("subtitle_uid") or ""))
            if subtitle is None and row.get("subtitle_index") is not None:
                subtitle = subtitle_by_index.get(int(row.get("subtitle_index") or 0))
            native_text_material_word = bool(row.get("native_words_schema") or row.get("native_words_path") or material_id)
            native_relative_timing = row.get("native_timing_scope") in {"unknown", "range"} and (
                row.get("source_start_us") is None or row.get("source_end_us") is None
            )
            requires_native_mapping = (
                (native_text_material_word or native_relative_timing)
                and (row.get("source_start_us") is None or row.get("source_end_us") is None)
            )
            if requires_native_mapping:
                relative_time_count += 1
            before_source_start = row.get("source_start_us")
            before_source_end = row.get("source_end_us")
            if subtitle:
                mapped_to_text_segment_count += 1
                if not row.get("subtitle_uid"):
                    row["subtitle_uid"] = str(subtitle.get("subtitle_uid") or "")
                if row.get("subtitle_index") is None:
                    row["subtitle_index"] = int(subtitle.get("subtitle_index") or index)
                row = self._convert_native_word_time(row, subtitle, primary_windows)
                basis = str(row.get("native_word_time_basis") or "")
                if basis == "relative_to_text_segment":
                    time_basis_counts["relative_to_text_segment_count"] += 1
                elif basis == "absolute_timeline":
                    time_basis_counts["absolute_timeline_count"] += 1
                elif row.get("native_mapping_error") == "NATIVE_WORD_TIME_BASIS_UNRESOLVED":
                    time_basis_counts["unresolved_count"] += 1
                if row.get("time_clamped_within_tolerance"):
                    time_clamped_within_tolerance_count += 1
            elif requires_native_mapping:
                blockers.append(
                    Blocker(
                        "NATIVE_WORD_TEXT_SEGMENT_BINDING_MISSING",
                        "native word uses relative timing but cannot bind to its owning text segment",
                        "ingest",
                        context={"word_id": str(row.get("word_id") or ""), "text_material_id": material_id},
                    )
                )
            has_source_time = (
                row.get("source_start_us") is not None
                and row.get("source_end_us") is not None
            ) or (
                not requires_native_mapping
                and row.get("start_us") is not None
                and row.get("end_us") is not None
            )
            if has_source_time:
                segment = self._source_segment_for_word(row, source_segments)
                if segment:
                    row["source_start_us"] = int(row.get("source_start_us") if row.get("source_start_us") is not None else row.get("start_us") or 0)
                    row["source_end_us"] = int(row.get("source_end_us") if row.get("source_end_us") is not None else row.get("end_us") or 0)
                    row["debug_hints"] = self._word_video_debug_hints(row, segment)
                    row["source_material_id"] = ""
                    row["source_segment_id"] = None
                else:
                    row.pop("source_material_id", None)
                    row.pop("source_segment_id", None)
                    blockers.append(
                        Blocker(
                            "V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING",
                            "speech timeline row source time is not covered by the primary video source",
                            "ingest",
                            context={
                                "word_id": str(row.get("word_id") or ""),
                                "source_start_us": row.get("source_start_us"),
                                "source_end_us": row.get("source_end_us"),
                            },
                        )
                    )
            elif not row.get("source_material_id") or not row.get("source_segment_id"):
                segment = self._source_segment_for_word(row, source_segments)
                if segment:
                    row["debug_hints"] = self._word_video_debug_hints(row, segment)
                    row["source_material_id"] = ""
                    row["source_segment_id"] = None
            if requires_native_mapping and (row.get("source_start_us") is None or row.get("source_end_us") is None):
                blockers.append(
                    Blocker(
                        str(row.get("native_mapping_error") or "NATIVE_WORD_SOURCE_MAPPING_FAILED"),
                        "native word relative timing could not be mapped to source media time",
                        "ingest",
                        context={
                            "word_id": str(row.get("word_id") or ""),
                            "text_material_id": material_id,
                            "subtitle_uid": str(row.get("subtitle_uid") or ""),
                            "start_us": row.get("start_us"),
                            "end_us": row.get("end_us"),
                        },
                    )
                )
            if row.get("source_start_us") is not None and row.get("source_end_us") is not None and self._source_segment_for_word(row, source_segments):
                mapped_to_source_segment_count += 1
            elif before_source_start is not None or before_source_end is not None:
                source_time_out_of_segment_count += 1
            if len(sample_mapped_words) < 10 and row.get("source_start_us") is not None:
                sample_mapped_words.append(
                    {
                        "word_id": str(row.get("word_id") or ""),
                        "text": str(row.get("word_text") or row.get("text") or ""),
                        "subtitle_index": row.get("subtitle_index"),
                        "source_start_us": row.get("source_start_us"),
                        "source_end_us": row.get("source_end_us"),
                        "current_video_segment_id": (row.get("debug_hints") or {}).get("current_video_segment_id"),
                        "current_video_window_index": (row.get("debug_hints") or {}).get("current_video_window_index"),
                    }
                )
            bound.append(row)
        monotonic_report = self._source_time_monotonic_report(bound)
        metadata = {
            "accepted_count": len(words),
            "mapped_to_text_segment_count": mapped_to_text_segment_count,
            "mapped_to_source_segment_count": mapped_to_source_segment_count,
            "primary_video_track_count": len({window.track_id for window in primary_windows}),
            "primary_video_segment_count": len(primary_windows),
            "primary_video_window_count": len(primary_windows),
            "primary_video_track_id": primary_windows[0].track_id if primary_windows else "",
            "relative_time_count": relative_time_count,
            "source_time_monotonic_by_subtitle": bool(monotonic_report["source_time_monotonic_by_subtitle"]),
            "source_time_out_of_segment_count": source_time_out_of_segment_count,
            "time_clamped_within_tolerance_count": time_clamped_within_tolerance_count,
            "native_word_time_basis": time_basis_counts,
            "segment_boundary_reset_count": int(monotonic_report["segment_boundary_reset_count"]),
            "source_time_non_monotonic_sample": monotonic_report["source_time_non_monotonic_sample"],
            "sample_mapped_words": sample_mapped_words,
        }
        if bound and not metadata["source_time_monotonic_by_subtitle"]:
            blockers.append(
                Blocker(
                    "NATIVE_WORD_SOURCE_TIME_NON_MONOTONIC_BY_SUBTITLE",
                    "native word source times are not monotonic in subtitle order",
                    "ingest",
                    context={"sample_mapped_words": sample_mapped_words, **monotonic_report["source_time_non_monotonic_sample"]},
                )
            )
        return bound, blockers, metadata

    def _convert_native_word_time(
        self,
        word: dict[str, Any],
        subtitle: dict[str, Any],
        primary_windows: list[PrimaryVideoWindow],
    ) -> dict[str, Any]:
        if word.get("source_start_us") is not None and word.get("source_end_us") is not None:
            return word
        start = int(word.get("start_us") or 0)
        end = int(word.get("end_us") or 0)
        subtitle_start = int(subtitle.get("start_us") or 0)
        subtitle_end = int(subtitle.get("end_us") or 0)
        subtitle_duration = max(0, subtitle_end - subtitle_start)
        if end <= start or subtitle_duration <= 0:
            row = dict(word)
            row["native_mapping_error"] = "NATIVE_WORD_TEXT_SEGMENT_BINDING_MISSING"
            return row

        target_start: int | None = None
        target_end: int | None = None
        timing_mode = "native_unknown"
        time_basis = ""
        clamped_within_tolerance = False
        if 0 <= start <= subtitle_duration and end <= subtitle_duration + TEXT_WORD_TIME_TOLERANCE_US:
            target_start = subtitle_start + start
            unclamped_target_end = subtitle_start + end
            target_end = min(unclamped_target_end, subtitle_end)
            clamped_within_tolerance = target_end != unclamped_target_end
            timing_mode = "relative_to_subtitle"
            time_basis = "relative_to_text_segment"
        elif 0 <= start <= subtitle_duration and end > subtitle_duration + TEXT_WORD_TIME_TOLERANCE_US:
            row = dict(word)
            row["native_mapping_error"] = "NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT"
            return row
        elif subtitle_start <= start <= subtitle_end and end <= subtitle_end + TEXT_WORD_TIME_TOLERANCE_US:
            target_start = start
            target_end = min(end, subtitle_end)
            clamped_within_tolerance = target_end != end
            timing_mode = "target_timeline"
            time_basis = "absolute_timeline"
        elif subtitle_start <= start <= subtitle_end and end > subtitle_end + TEXT_WORD_TIME_TOLERANCE_US:
            row = dict(word)
            row["native_mapping_error"] = "NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT"
            return row
        if target_start is None or target_end is None:
            row = dict(word)
            row["native_mapping_error"] = "NATIVE_WORD_TIME_BASIS_UNRESOLVED"
            return row
        if target_end <= target_start:
            row = dict(word)
            row["native_mapping_error"] = "NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT"
            return row

        window = self._video_window_for_target_time(target_start, target_end, primary_windows)
        row = dict(word)
        row["target_start_us"] = target_start
        row["target_end_us"] = target_end
        row["source_start_us"] = target_start
        row["source_end_us"] = target_end
        row["start_us"] = target_start
        row["end_us"] = target_end
        row["native_timing_mode"] = timing_mode
        row["native_word_time_basis"] = time_basis
        if clamped_within_tolerance:
            row["time_clamped_within_tolerance"] = True
        if window:
            debug_hints = dict(row.get("debug_hints") or {})
            debug_hints.update(self._window_debug_hints(window, target_start, target_end))
            row["debug_hints"] = debug_hints
            row["source_material_id"] = ""
            row["source_segment_id"] = None
            row["native_timing_mode"] = f"{timing_mode}_mapped_to_primary_video_timeline"
        else:
            row["native_mapping_error"] = "V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING"
        return row

    def _source_time_monotonic_report(self, words: list[dict[str, Any]]) -> dict[str, Any]:
        sortable = [
            (
                int(row.get("subtitle_index") or 0),
                int(row.get("word_index_in_subtitle") or 0),
                int(row.get("source_start_us") or row.get("start_us") or 0),
                int((row.get("debug_hints") or {}).get("current_video_window_index") or 0),
                str((row.get("debug_hints") or {}).get("current_video_segment_id") or ""),
                str((row.get("debug_hints") or {}).get("current_text_segment_id") or row.get("subtitle_uid") or ""),
                str(row.get("word_id") or ""),
                str(row.get("subtitle_uid") or ""),
                str(row.get("source_segment_id") or ""),
            )
            for row in words
            if row.get("subtitle_index") is not None and (row.get("source_start_us") is not None or row.get("start_us") is not None)
        ]
        previous: tuple[int, str, int, str] | None = None
        previous_window_index = 0
        segment_boundary_reset_count = 0
        for subtitle_index, _word_index, source_start, window_index, video_segment_id, text_segment_id, word_id, subtitle_uid, source_segment_id in sorted(sortable):
            if previous_window_index and window_index != previous_window_index:
                segment_boundary_reset_count += 1
            previous_window_index = window_index
            if previous is not None and source_start < previous[0]:
                return {
                    "source_time_monotonic_by_subtitle": False,
                    "segment_boundary_reset_count": segment_boundary_reset_count,
                    "source_time_non_monotonic_sample": {
                        "subtitle_index": subtitle_index,
                        "word_id": word_id,
                        "prev_word_id": previous[1],
                        "prev_canonical_source_start_us": previous[0],
                        "current_canonical_source_start_us": source_start,
                        "prev_source_start_us": previous[0],
                        "current_source_start_us": source_start,
                        "prev_window_index": previous[2],
                        "current_window_index": window_index,
                        "prev_text_segment_id": previous[3],
                        "current_text_segment_id": text_segment_id,
                        "current_video_segment_id": video_segment_id,
                        "source_segment_id": source_segment_id,
                        "subtitle_uid": subtitle_uid,
                    },
                }
            previous = (source_start, word_id, window_index, text_segment_id)
        return {
            "source_time_monotonic_by_subtitle": True,
            "segment_boundary_reset_count": segment_boundary_reset_count,
            "source_time_non_monotonic_sample": {},
        }

    def _source_segment_for_word(self, word: dict[str, Any], source_segments: list[dict[str, Any]]) -> dict[str, Any] | None:
        start = int(word.get("source_start_us") or word.get("start_us") or 0)
        end = int(word.get("source_end_us") or word.get("end_us") or 0)
        for segment in source_segments:
            if "video" not in str(segment.get("track_type") or segment.get("type") or "").lower():
                continue
            seg_start = int(segment.get("canonical_source_start_us") or segment.get("target_start_us") or segment.get("source_start_us") or 0)
            seg_end = int(segment.get("canonical_source_end_us") or segment.get("target_end_us") or segment.get("source_end_us") or 0)
            if seg_start <= start and end <= seg_end:
                return segment
        return None

    def _source_segment_for_target_time(
        self,
        target_start: int,
        target_end: int,
        source_segments: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for segment in source_segments:
            if "video" not in str(segment.get("track_type") or segment.get("type") or "").lower():
                continue
            seg_start = int(segment.get("target_start_us") or 0)
            seg_end = int(segment.get("target_end_us") or 0)
            if seg_start <= target_start and target_end <= seg_end:
                return segment
        return None

    def _primary_video_windows(self, source_segments: list[dict[str, Any]]) -> tuple[list[PrimaryVideoWindow], list[Blocker]]:
        by_track: dict[str, list[dict[str, Any]]] = {}
        for segment in source_segments:
            if "video" not in str(segment.get("track_type") or segment.get("type") or "").lower():
                continue
            target_start = int(segment.get("canonical_source_start_us") or segment.get("target_start_us") or 0)
            target_end = int(segment.get("canonical_source_end_us") or segment.get("target_end_us") or 0)
            material_id = str(segment.get("material_id") or segment.get("materialId") or segment.get("source_material_id") or "")
            track_id = str(segment.get("track_id") or "")
            if not track_id or not material_id or target_end <= target_start:
                continue
            by_track.setdefault(track_id, []).append(segment)
        if not by_track:
            return [], [
                Blocker(
                    "V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING",
                    "native speech timeline requires a source-backed primary video track",
                    "ingest",
                    context={"reason": "no video track target windows"},
                )
            ]
        scored: list[tuple[int, str, list[dict[str, Any]]]] = []
        for track_id, rows in by_track.items():
            coverage = sum(
                max(
                    0,
                    int(row.get("canonical_source_end_us") or row.get("target_end_us") or 0)
                    - int(row.get("canonical_source_start_us") or row.get("target_start_us") or 0),
                )
                for row in rows
            )
            scored.append((coverage, track_id, rows))
        max_coverage = max(item[0] for item in scored)
        winners = [item for item in scored if item[0] == max_coverage]
        if len(winners) != 1:
            return [], [
                Blocker(
                    "V21_SPEECH_TIMELINE_PRIMARY_VIDEO_AMBIGUOUS",
                    "multiple video tracks are equally plausible speech source tracks",
                    "ingest",
                    context={"candidate_track_ids": sorted(item[1] for item in winners)},
                )
            ]
        _coverage, track_id, rows = winners[0]
        windows: list[PrimaryVideoWindow] = []
        for index, segment in enumerate(
            sorted(rows, key=lambda row: int(row.get("canonical_source_start_us") or row.get("target_start_us") or 0)),
            start=1,
        ):
            target_start = int(segment.get("canonical_source_start_us") or segment.get("target_start_us") or 0)
            target_end = int(segment.get("canonical_source_end_us") or segment.get("target_end_us") or 0)
            source_start = int(segment.get("material_local_source_start_us") or 0)
            source_end = int(segment.get("material_local_source_end_us") or 0)
            if source_end <= source_start:
                source_time = _timerange(segment, "source_timerange")
                source_start = int(source_time.get("start_us") or 0)
                source_end = int(source_time.get("end_us") or 0)
            windows.append(
                PrimaryVideoWindow(
                    track_id=track_id,
                    segment_id=str(segment.get("id") or ""),
                    material_id=str(segment.get("material_id") or segment.get("materialId") or segment.get("source_material_id") or ""),
                    target_start_us=target_start,
                    target_end_us=target_end,
                    material_local_source_start_us=source_start,
                    material_local_source_end_us=source_end,
                    speed=self._segment_speed_for_window(segment),
                    window_index=index,
                    target_duration_us=max(0, target_end - target_start),
                )
            )
        return windows, []

    def _video_window_for_target_time(
        self,
        target_start: int,
        target_end: int,
        primary_windows: list[PrimaryVideoWindow],
    ) -> PrimaryVideoWindow | None:
        matches = [
            window
            for window in primary_windows
            if window.target_start_us <= int(target_start) and int(target_end) <= window.target_end_us
        ]
        return matches[0] if len(matches) == 1 else None

    def _window_debug_hints(
        self,
        window: PrimaryVideoWindow,
        target_start: int,
        target_end: int,
    ) -> dict[str, Any]:
        material_start = window.material_local_source_start_us + int(round((int(target_start) - window.target_start_us) * window.speed))
        material_end = window.material_local_source_start_us + int(round((int(target_end) - window.target_start_us) * window.speed))
        return {
            "current_video_track_id": window.track_id,
            "current_video_segment_id": window.segment_id,
            "current_video_material_id": window.material_id,
            "current_video_window_index": window.window_index,
            "current_video_window_target_start_us": window.target_start_us,
            "current_video_window_target_end_us": window.target_end_us,
            "material_local_source_start_us": material_start,
            "material_local_source_end_us": material_end,
            "material_local_source_window_start_us": window.material_local_source_start_us,
            "material_local_source_window_end_us": window.material_local_source_end_us,
            "speed": window.speed,
        }

    def _word_video_debug_hints(self, word: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
        debug_hints = dict(word.get("debug_hints") or {})
        target_start = int(word.get("source_start_us") or word.get("start_us") or 0)
        target_end = int(word.get("source_end_us") or word.get("end_us") or 0)
        target_window_start = int(segment.get("canonical_source_start_us") or segment.get("target_start_us") or 0)
        target_window_end = int(segment.get("canonical_source_end_us") or segment.get("target_end_us") or 0)
        source_window_start = int(segment.get("material_local_source_start_us") or 0)
        speed = self._segment_speed_for_window(segment)
        debug_hints.update(
            {
                "current_video_track_id": str(segment.get("track_id") or ""),
                "current_video_segment_id": str(segment.get("id") or ""),
                "current_video_material_id": str(segment.get("material_id") or segment.get("materialId") or segment.get("source_material_id") or ""),
                "current_video_window_target_start_us": target_window_start,
                "current_video_window_target_end_us": target_window_end,
                "material_local_source_start_us": source_window_start + int(round((target_start - target_window_start) * speed)),
                "material_local_source_end_us": source_window_start + int(round((target_end - target_window_start) * speed)),
                "speed": speed,
            }
        )
        return debug_hints

    def _segment_speed_for_window(self, segment: dict[str, Any]) -> float:
        for key in ("speed", "speed_ratio", "source_speed"):
            value = segment.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        extra = segment.get("extra")
        if isinstance(extra, dict):
            for key in ("speed", "speed_ratio"):
                value = extra.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
        source_time = _timerange(segment, "source_timerange")
        target_time = _timerange(segment, "target_timerange")
        source_duration = int(source_time.get("duration_us") or 0)
        target_duration = int(target_time.get("duration_us") or 0)
        if source_duration > 0 and target_duration > 0:
            return round(source_duration / target_duration, 4)
        return 1.0
