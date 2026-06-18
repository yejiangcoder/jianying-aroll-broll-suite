from __future__ import annotations

import re
from typing import Any

from aroll_v21.ir.models import CanonicalSourceGraph, CaptionRenderUnit


_NORMALIZED_SUBTITLE_RE = re.compile(r"^sub_(\d+)$", re.IGNORECASE)


class SubtitleIdentityResolver:
    """Resolve caption subtitle references to real text material ids.

    External word timelines may use normalized ids such as ``sub_000001``
    while real Jianying text segments keep UUID-like ids. The resolver maps
    both forms through SourceGraph subtitle rows and subtitle_index.
    """

    def material_ids_for_captions(
        self,
        source_graph: CanonicalSourceGraph,
        captions: list[CaptionRenderUnit] | None,
    ) -> set[str]:
        requested_uids = {uid for caption in (captions or []) for uid in caption.source_subtitle_uids}
        if not requested_uids:
            return self._material_ids_for_rows(source_graph.subtitle_rows)

        rows_by_uid: dict[str, dict[str, Any]] = {}
        rows_by_index: dict[int, dict[str, Any]] = {}
        for row in source_graph.subtitle_rows:
            subtitle_uid = str(row.get("subtitle_uid") or row.get("fragment_id") or "")
            if subtitle_uid:
                rows_by_uid[subtitle_uid] = row
            if row.get("subtitle_index") is not None:
                rows_by_index[int(row.get("subtitle_index") or 0)] = row

        matched_rows: list[dict[str, Any]] = []
        for uid in requested_uids:
            row = rows_by_uid.get(uid)
            if row is None:
                normalized_index = self._normalized_subtitle_index(uid)
                if normalized_index is not None:
                    row = rows_by_index.get(normalized_index)
            if row is not None:
                matched_rows.append(row)
        return self._material_ids_for_rows(matched_rows)

    def _normalized_subtitle_index(self, uid: str) -> int | None:
        match = _NORMALIZED_SUBTITLE_RE.match(str(uid or ""))
        if not match:
            return None
        return int(match.group(1))

    def _material_ids_for_rows(self, rows: list[dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for row in rows:
            material_id = str(row.get("text_material_id") or "")
            if not material_id and isinstance(row.get("segment"), dict):
                material_id = str(row["segment"].get("material_id") or row["segment"].get("materialId") or "")
            if not material_id and isinstance(row.get("material"), dict):
                material_id = str(row["material"].get("id") or "")
            if material_id:
                ids.add(material_id)
        return ids
