from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline
from aroll_v21.ingest.external_word_timeline_adapter import ExternalWordTimelineAdapter
from aroll_v21.ir.models import Blocker


NO_TIMERANGE = None
NO_SOURCE_SEGMENT = None


@dataclass(frozen=True)
class WordTimelineProviderResult:
    words: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class WordTimelineProvider(Protocol):
    def load(
        self,
        *,
        draft_data: dict[str, Any],
        external_path: Path | None = None,
        text_materials: list[dict[str, Any]] | None = None,
        text_segments: list[dict[str, Any]] | None = None,
        source_segments: list[dict[str, Any]] | None = None,
    ) -> WordTimelineProviderResult:
        ...


class ExternalWordTimelineProvider:
    def __init__(self, adapter: ExternalWordTimelineAdapter | None = None) -> None:
        self.adapter = adapter or ExternalWordTimelineAdapter()

    def load(self, path: Path) -> WordTimelineProviderResult:
        result = self.adapter.load(path)
        return WordTimelineProviderResult(words=result.words, blockers=result.blockers, metadata=result.metadata)


class DraftNativeWordTimelineProvider:
    def load(
        self,
        draft_data: dict[str, Any],
        *,
        text_materials: list[dict[str, Any]] | None = None,
        text_segments: list[dict[str, Any]] | None = None,
        source_segments: list[dict[str, Any]] | None = None,
    ) -> WordTimelineProviderResult:
        words, metadata = discover_draft_native_word_timeline(
            draft_data,
            text_materials=text_materials,
            text_segments=text_segments,
            source_segments=source_segments,
        )
        blockers: list[Blocker] = []
        if not words and int(metadata.get("candidate_count") or 0) > 0 and int(metadata.get("accepted_count") or 0) == 0:
            blockers.append(
                Blocker(
                    "DRAFT_NATIVE_WORD_ROWS_REJECTED",
                    "draft-native word rows were found but none matched the required word-level schema",
                    "ingest",
                    context={
                        "candidate_count": int(metadata.get("candidate_count") or 0),
                        "rejected_count": int(metadata.get("rejected_count") or 0),
                        "sample_rejections": metadata.get("sample_rejections") or [],
                    },
                )
            )
        metadata = dict(metadata)
        metadata.update(
            {
                "speech_timeline_provider": "draft_native_word",
                "speech_timeline_granularity": "word",
                "precision": "word",
                "can_cut_inside_caption": True,
            }
        )
        return WordTimelineProviderResult(words=words, blockers=blockers, metadata=metadata)


class DraftNativeSubtitlePhraseTimelineProvider:
    def load(
        self,
        *,
        text_materials: list[dict[str, Any]] | None = None,
        text_segments: list[dict[str, Any]] | None = None,
        source_segments: list[dict[str, Any]] | None = None,
    ) -> WordTimelineProviderResult:
        text_materials = text_materials or []
        text_segments = text_segments or []
        source_segments = [row for row in (source_segments or []) if "video" in str(row.get("track_type") or row.get("type") or "").lower()]
        material_by_id = {str(row.get("id") or ""): row for row in text_materials if str(row.get("id") or "")}
        words: list[dict[str, Any]] = []
        blockers: list[Blocker] = []
        too_coarse_count = 0
        for index, segment in enumerate(text_segments, start=1):
            material_id = str(segment.get("material_id") or segment.get("materialId") or "")
            text = self._material_text(material_by_id.get(material_id) or {})
            if not text:
                continue
            target_range = self._timerange(segment.get("target_timerange"))
            if target_range is None:
                continue
            source_segment = self._source_segment_for_target_time(target_range[0], target_range[1], source_segments)
            if source_segment is None:
                blockers.append(
                    Blocker(
                        "V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING",
                        "subtitle phrase timeline cannot map caption time to a primary video source segment",
                        "ingest",
                        context={"subtitle_segment_id": str(segment.get("id") or ""), "target_range": list(target_range)},
                    )
                )
                continue
            source_start = target_range[0]
            source_end = target_range[1]
            if source_end <= source_start:
                continue
            if source_end - source_start > 12_000_000 or len(text) > 80:
                too_coarse_count += 1
            words.append(
                {
                    "word_id": f"subtitle_phrase_{index:06d}",
                    "word_text": text,
                    "start_us": source_start,
                    "end_us": source_end,
                    "subtitle_uid": str(segment.get("id") or f"subtitle_phrase_{index:06d}"),
                    "subtitle_index": index,
                    "is_cuttable_left": True,
                    "is_cuttable_right": True,
                    "speech_timeline_granularity": "subtitle_phrase",
                    "precision": "coarse",
                    "can_cut_inside_caption": False,
                    "debug_hints": {
                        "speech_timeline_granularity": "subtitle_phrase",
                        "subtitle_phrase_coarse_provider": True,
                        "current_video_segment_id": str(source_segment.get("id") or ""),
                        "current_video_material_id": str(
                            source_segment.get("material_id") or source_segment.get("materialId") or source_segment.get("source_material_id") or ""
                        ),
                        "canonical_source_coordinate": "primary_video_target_timeline",
                    },
                }
            )
        if too_coarse_count:
            blockers.append(
                Blocker(
                    "V21_SUBTITLE_PHRASE_TIMELINE_TOO_COARSE",
                    "subtitle phrase timeline contains long coarse captions",
                    "ingest",
                    severity="warning",
                    context={"too_coarse_count": too_coarse_count},
                )
            )
        return WordTimelineProviderResult(
            words=words,
            blockers=blockers,
            metadata={
                "provider": "draft_native_subtitle_phrase",
                "speech_timeline_provider": "draft_native_subtitle_phrase",
                "speech_timeline_granularity": "subtitle_phrase",
                "precision": "coarse",
                "can_cut_inside_caption": False,
                "accepted_count": len(words),
                "subtitle_phrase_count": len(words),
            },
        )

    def _timerange(self, value: Any) -> tuple[int, int] | None:
        if not isinstance(value, dict):
            return NO_TIMERANGE
        start = int(value.get("start") or 0)
        duration = int(value.get("duration") or 0)
        end = int(value.get("end") or (start + duration if duration else 0))
        return (start, end) if end > start else NO_TIMERANGE

    def _source_segment_for_target_time(
        self,
        target_start: int,
        target_end: int,
        source_segments: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for segment in source_segments:
            seg_start = int(segment.get("target_start_us") or 0)
            seg_end = int(segment.get("target_end_us") or 0)
            if seg_start <= target_start and target_end <= seg_end:
                return segment
        return NO_SOURCE_SEGMENT

    def _material_text(self, material: dict[str, Any]) -> str:
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


class FutureAsrWordTimelineProvider:
    def load(self, *_args: Any, **_kwargs: Any) -> WordTimelineProviderResult:
        return WordTimelineProviderResult(
            blockers=[
                Blocker(
                    "ASR_WORD_TIMELINE_PROVIDER_NOT_IMPLEMENTED",
                    "future ASR word timeline provider is a contract only and is not enabled",
                    "ingest",
                    severity="warning",
                )
            ],
            metadata={"provider": "future_asr", "available": False},
        )


class DefaultWordTimelineProvider:
    def __init__(
        self,
        *,
        external_provider: ExternalWordTimelineProvider | None = None,
        draft_native_provider: DraftNativeWordTimelineProvider | None = None,
        subtitle_phrase_provider: DraftNativeSubtitlePhraseTimelineProvider | None = None,
        future_asr_provider: FutureAsrWordTimelineProvider | None = None,
    ) -> None:
        self.external_provider = external_provider or ExternalWordTimelineProvider()
        self.draft_native_provider = draft_native_provider or DraftNativeWordTimelineProvider()
        self.subtitle_phrase_provider = subtitle_phrase_provider or DraftNativeSubtitlePhraseTimelineProvider()
        self.future_asr_provider = future_asr_provider or FutureAsrWordTimelineProvider()

    def load(
        self,
        *,
        draft_data: dict[str, Any],
        external_path: Path | None = None,
        text_materials: list[dict[str, Any]] | None = None,
        text_segments: list[dict[str, Any]] | None = None,
        source_segments: list[dict[str, Any]] | None = None,
    ) -> WordTimelineProviderResult:
        if external_path is not None:
            result = self.external_provider.load(external_path)
            metadata = dict(result.metadata)
            metadata.update(
                {
                    "speech_timeline_provider": "external_clean_word_timeline",
                    "speech_timeline_granularity": "word",
                    "precision": "word",
                    "can_cut_inside_caption": True,
                }
            )
            return WordTimelineProviderResult(
                words=result.words,
                blockers=result.blockers,
                metadata={
                    "selected_provider": "external",
                    "speech_timeline_provider": "external_clean_word_timeline",
                    "speech_timeline_granularity": "word",
                    "precision": "word",
                    "can_cut_inside_caption": True,
                    "external": metadata,
                },
            )
        native = self.draft_native_provider.load(
            draft_data,
            text_materials=text_materials,
            text_segments=text_segments,
            source_segments=source_segments,
        )
        if native.words:
            return WordTimelineProviderResult(
                words=native.words,
                blockers=native.blockers,
                metadata={
                    "selected_provider": "draft_native_word",
                    "speech_timeline_provider": "draft_native_word",
                    "speech_timeline_granularity": "word",
                    "precision": "word",
                    "can_cut_inside_caption": True,
                    "draft_native": native.metadata,
                },
            )
        subtitle_phrase = self.subtitle_phrase_provider.load(
            text_materials=text_materials,
            text_segments=text_segments,
            source_segments=source_segments,
        )
        if subtitle_phrase.words:
            return WordTimelineProviderResult(
                words=subtitle_phrase.words,
                blockers=list(native.blockers) + list(subtitle_phrase.blockers),
                metadata={
                    "selected_provider": "draft_native_subtitle_phrase",
                    "speech_timeline_provider": "draft_native_subtitle_phrase",
                    "speech_timeline_granularity": "subtitle_phrase",
                    "precision": "coarse",
                    "can_cut_inside_caption": False,
                    "draft_native": native.metadata,
                    "subtitle_phrase": subtitle_phrase.metadata,
                },
            )
        future = self.future_asr_provider.load()
        blockers = list(native.blockers) + [
            Blocker(
                "REAL_DRAFT_SPEECH_TIMELINE_MISSING",
                "real draft does not expose a legal word/token timeline or subtitle phrase timeline",
                "ingest",
                context={"draft_native": native.metadata, "subtitle_phrase": subtitle_phrase.metadata, "future_asr": future.metadata},
            )
        ]
        return WordTimelineProviderResult(
            words=[],
            blockers=blockers,
            metadata={
                "selected_provider": "",
                "speech_timeline_provider": "",
                "speech_timeline_granularity": "",
                "precision": "",
                "can_cut_inside_caption": False,
                "draft_native": native.metadata,
                "subtitle_phrase": subtitle_phrase.metadata,
                "future_asr": future.metadata,
            },
        )
