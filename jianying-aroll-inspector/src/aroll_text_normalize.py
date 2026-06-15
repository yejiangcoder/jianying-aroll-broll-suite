from __future__ import annotations

import difflib
import re
from typing import Iterable


PUNCT_RE = re.compile(r"[\s，。！？、,.!?：:；;（）()\[\]【】「」『』\"'“”‘’·…—\-]")
FILLER_RE = re.compile(r"(啊|呐|呢|吧|嘛|哎|诶|额|嗯|呃|这个|那个)")
WEAK_PREFIX_WORDS = ("就是", "就", "这", "这个", "然后", "但是", "但", "所以", "因为", "如果")
DEFAULT_PROTECTED_TERMS = (
)


def compact_text(text: str) -> str:
    return PUNCT_RE.sub("", text or "")


def normalize_pronouns(text: str) -> str:
    text = text or ""
    text = re.sub(r"[她它]们", "他们", text)
    text = re.sub(r"[她它]", "他", text)
    return text


def normalize_text(text: str, *, pronouns: bool = True, weak: bool = False, stutter: bool = False) -> str:
    out = normalize_pronouns(text) if pronouns else (text or "")
    out = compact_text(out)
    if weak:
        out = FILLER_RE.sub("", out)
        changed = True
        while changed:
            changed = False
            for word in WEAK_PREFIX_WORDS:
                if out.startswith(word) and len(out) > len(word) + 2:
                    out = out[len(word):]
                    changed = True
    if stutter:
        out = compress_repeated_chars(out)
    return out


def compress_repeated_chars(text: str) -> str:
    return re.sub(r"(.)\1+", r"\1", text or "")


def char_ngrams(text: str, n: int = 2) -> set[str]:
    text = text or ""
    if len(text) <= n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(0, len(text) - n + 1)}


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    aset = set(a)
    bset = set(b)
    if not aset and not bset:
        return 1.0
    if not aset or not bset:
        return 0.0
    return len(aset & bset) / len(aset | bset)


def lcs_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    match_len = sum(block.size for block in matcher.get_matching_blocks())
    return (2.0 * match_len) / (len(a) + len(b))


def edit_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def similarity(a: str, b: str) -> dict[str, float | bool]:
    norm_a = normalize_text(a)
    norm_b = normalize_text(b)
    pron_a = normalize_text(a, pronouns=True, weak=True, stutter=True)
    pron_b = normalize_text(b, pronouns=True, weak=True, stutter=True)
    return {
        "lcs_ratio": round(lcs_ratio(norm_a, norm_b), 4),
        "jaccard": round(jaccard(char_ngrams(norm_a, 2), char_ngrams(norm_b, 2)), 4),
        "edit_ratio": round(edit_ratio(norm_a, norm_b), 4),
        "pronoun_weak_lcs_ratio": round(lcs_ratio(pron_a, pron_b), 4),
        "pronoun_weak_edit_ratio": round(edit_ratio(pron_a, pron_b), 4),
        "prefix_containment": bool(norm_a and norm_b and (norm_a.startswith(norm_b) or norm_b.startswith(norm_a))),
        "substring_containment": bool(norm_a and norm_b and (norm_a in norm_b or norm_b in norm_a)),
    }


def protected_atoms_in(text: str, atoms: Iterable[str] | None = None) -> list[str]:
    norm = normalize_text(text)
    protected = tuple(atoms) if atoms is not None else DEFAULT_PROTECTED_TERMS
    return [atom for atom in protected if normalize_text(atom) in norm]


def repeated_phrase_spans(text: str, max_phrase_len: int = 8) -> list[dict[str, object]]:
    norm = compact_text(text)
    found: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()
    for start in range(len(norm)):
        for size in range(1, max_phrase_len + 1):
            a = norm[start : start + size]
            b = norm[start + size : start + 2 * size]
            if not a or len(b) < len(a):
                continue
            if a == b:
                key = (start, size, a)
                if key not in seen:
                    found.append(
                        {
                            "phrase": a,
                            "start_char": start,
                            "phrase_len": size,
                            "repeat_count": 2,
                        }
                    )
                    seen.add(key)
    return found
