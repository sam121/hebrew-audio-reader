#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TRANSCRIPT = ROOT / "transcript.json"
SOURCE_INDEX = ROOT / "index.html"
SOURCE_QA = ROOT / "qa.html"
SOURCE_ANNOTATE = ROOT / "annotate.html"
SOURCE_QA_SYNC_CONFIG = ROOT / "qa-sync-config.json"
SOURCE_PAGES = ROOT / "pages"
SITE_ROOT = ROOT / "site"
SITE_DATA = SITE_ROOT / "data"
SITE_AUDIO = SITE_ROOT / "assets" / "audio"
SITE_LINE_STRIPS = SITE_ROOT / "assets" / "line-strips"

DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_SEQUENCE_GAP_MS = 220
DEFAULT_MIXED_SEGMENT_GAP_MS = 150
DEFAULT_BLOCK_SEGMENT_GAP_MS = 170
TRAILING_PUNCTUATION = ",.;:!?\"'״׳…׃"
HEBREW_CHAR_RE = re.compile(r"[\u0590-\u05FF]")
LATIN_CHAR_RE = re.compile(r"[A-Za-z]")
DOT_SENSITIVE_MARKERS = ("ּ", "ׁ", "ׂ")
DOT_SENSITIVE_PATTERNS = ("וּ", "וֹ")
QA_PRIORITY_PAGES = [1, 2, 12, 39, 48, 61]
HEBREW_MARKS_ONLY_RE = re.compile(r"^[\u0591-\u05C7]+$")
HEBREW_LETTER_AND_MARKS_RE = re.compile(r"^[\u05D0-\u05EA\u0591-\u05C7]+$")
STANDALONE_VOWEL_NAMES = {
    "ַ": "פַּתָּח",
    "ָ": "קָמָץ",
    "ֶ": "סֶגוֹל",
    "ֵ": "צֵירֵי",
    "ִ": "חִירִיק",
    "ֻ": "קֻבּוּץ",
    "ֹ": "חוֹלָם",
    "וֹ": "חוֹלָם",
    "וּ": "שׁוּרוּק",
    "ְ": "שְׁוָה",
    "ֱ": "חֲטַף סֶגּוֹל",
    "ֲ": "חֲטַף פַּתָּח",
    "ֳ": "חֲטַף קָמָץ",
}
ENGLISH_VOWEL_LABEL_HINTS = {
    "ַ": ("patach",),
    "ָ": ("kamatz",),
    "ֶ": ("segol",),
    "ֵ": ("tzeiri", "tzere", "tzeirei"),
    "ִ": ("chirik", "hirik"),
    "ֻ": ("kubutz", "qubuts", "kubuts"),
    "ֹ": ("cholam", "holam"),
    "וֹ": ("cholam", "holam"),
    "וּ": ("shuruk", "shuruk"),
    "ְ": ("sheva", "shva"),
    "ֱ": ("chataf segol",),
    "ֲ": ("chataf patach",),
    "ֳ": ("chataf kamatz",),
}
ISOLATED_HEBREW_AUDIO_OVERRIDES = {
    "בּ": "בֶּה",
}
ENGLISH_AUDIO_TEXT_REPLACEMENTS = (
    (re.compile(r"\bBerachah\b", re.IGNORECASE), "beh-rah-khah"),
    (re.compile(r"\bsiddur\b", re.IGNORECASE), "sid-door"),
)
LEADING_CONTINUATION_RE = re.compile(r'^[\s"\(\[\{“‘\'\-]*[a-z]')
TITLE_CASE_RE = re.compile(r"^[A-Z][A-Za-z'’-]*$")
HEADER_PREFIXES = ("blessing ", "read this", "read these", "the blessing")


class BuildError(Exception):
    pass


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def stable_hash(payload: Dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def copy_static_assets() -> None:
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_INDEX, SITE_ROOT / "index.html")
    if SOURCE_QA.exists():
        shutil.copy2(SOURCE_QA, SITE_ROOT / "qa.html")
    if SOURCE_ANNOTATE.exists():
        shutil.copy2(SOURCE_ANNOTATE, SITE_ROOT / "annotate.html")
    if SOURCE_QA_SYNC_CONFIG.exists():
        shutil.copy2(SOURCE_QA_SYNC_CONFIG, SITE_DATA / "qa-sync-config.json")

    if SOURCE_PAGES.exists():
        destination = SITE_ROOT / "pages"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(SOURCE_PAGES, destination)

    if SITE_LINE_STRIPS.exists():
        shutil.rmtree(SITE_LINE_STRIPS)


def elevenlabs_request(
    *,
    api_key: str,
    voice_id: str,
    text: str,
    model_id: str,
    output_format: str,
    language_code: Optional[str],
) -> bytes:
    query = urlencode({"output_format": output_format})
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?{query}"
    payload = {
        "text": text,
        "model_id": model_id,
    }

    if language_code:
        payload["language_code"] = language_code

    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BuildError(f"ElevenLabs returned {exc.code} for text '{text}': {body}") from exc
    except URLError as exc:
        raise BuildError(f"ElevenLabs request failed for text '{text}': {exc}") from exc


def ensure_audio(
    *,
    category: str,
    language: str,
    language_code: Optional[str],
    item_id: str,
    text: Optional[str],
    model_id: str,
    voice_id: Optional[str],
    voice_secret_name: str,
    api_key: Optional[str],
    output_format: str,
    allow_missing_audio: bool,
    manifest_entries: List[Dict],
    missing_items: List[Dict],
    revision: Optional[str] = None,
) -> Optional[str]:
    if not text:
        return None

    hash_input = {
        "category": category,
        "language": language,
        "model_id": model_id,
        "output_format": output_format,
        "revision": revision or "",
        "text": text,
        "voice_id": voice_id,
    }
    filename = stable_hash(hash_input) + ".mp3"
    relative_path = f"assets/audio/{language}/{category}/{filename}"
    output_path = SITE_ROOT / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        manifest_entries.append(
            {
                "id": item_id,
                "language": language,
                "category": category,
                "status": "reused",
                "path": relative_path,
                "text": text,
                "model_id": model_id,
            }
        )
        return relative_path

    if not api_key or not voice_id:
        missing_items.append(
            {
                "id": item_id,
                "language": language,
                "category": category,
                "reason": "missing_credentials",
                "text": text,
            }
        )
        if allow_missing_audio:
            return None
        raise BuildError(
            f"Audio for {item_id} is missing and cannot be generated without "
            f"{'ELEVENLABS_API_KEY' if not api_key else voice_secret_name}."
        )

    audio_bytes = elevenlabs_request(
        api_key=api_key,
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=output_format,
        language_code=language_code,
    )
    output_path.write_bytes(audio_bytes)
    manifest_entries.append(
        {
            "id": item_id,
            "language": language,
            "category": category,
            "status": "generated",
            "path": relative_path,
            "text": text,
            "model_id": model_id,
        }
    )
    return relative_path


def clone_word(word: Dict) -> Dict:
    clone = dict(word)
    clone["audio"] = {
        "he": {
            "word": None
        }
    }
    return clone


def clone_line(line: Dict) -> Dict:
    clone = dict(line)
    clone["audio"] = {
        "he": {
            "line": None
        },
        "en": {
            "line": None
        },
        "mixed": {
            "line": None,
            "segments": [],
            "gapMs": 0,
        }
    }
    clone["stripImage"] = None
    clone["playback"] = {"urls": [], "gapMs": 0, "mode": "missing", "segments": []}
    return clone


def clone_section(section: Dict) -> Dict:
    clone = dict(section)
    clone["audio"] = {
        "mixed": {
            "block": None,
            "segments": [],
            "gapMs": 0,
        }
    }
    return clone


def clone_spoken_block(block: Dict) -> Dict:
    clone = dict(block)
    clone["lineIds"] = list(block.get("lineIds", []))
    clone["lineNumbers"] = list(block.get("lineNumbers", []))
    clone["playback"] = {"urls": [], "gapMs": 0, "mode": "missing"}
    clone["segments"] = []
    return clone


def ordered_words(page: Dict) -> List[Dict]:
    return sorted(page.get("words", []), key=lambda item: item["order"])


def ordered_lines(page: Dict) -> List[Dict]:
    return sorted(page.get("lines", []), key=lambda item: item["order"])


def ordered_sections(page: Dict) -> List[Dict]:
    return sorted(page.get("sections", []), key=lambda item: item["order"])


def trailing_punctuation(text: Optional[str]) -> str:
    if not text:
        return ""

    stripped = text.rstrip()
    suffix: List[str] = []
    for character in reversed(stripped):
        if character not in TRAILING_PUNCTUATION:
            break
        suffix.append(character)
    return "".join(reversed(suffix))


def script_for_character(character: str) -> Optional[str]:
    if HEBREW_CHAR_RE.search(character):
        return "he"
    if LATIN_CHAR_RE.search(character):
        return "en"
    return None


def split_mixed_text_segments(text: Optional[str]) -> List[Dict[str, str]]:
    raw_text = (text or "").strip()
    if not raw_text:
        return []

    segments: List[Dict[str, str]] = []
    current_script: Optional[str] = None
    current_chars: List[str] = []
    pending_prefix: List[str] = []

    for character in raw_text:
        script = script_for_character(character)
        if script is None:
            if current_script is None:
                pending_prefix.append(character)
            else:
                current_chars.append(character)
            continue

        if current_script is None:
            current_script = script
            current_chars = pending_prefix + [character]
            pending_prefix = []
            continue

        if script == current_script:
            current_chars.append(character)
            continue

        segment_text = "".join(current_chars).strip()
        if segment_text:
            segments.append({"language": current_script, "text": segment_text})

        current_script = script
        current_chars = [character]

    segment_text = "".join(current_chars).strip()
    if segment_text and current_script:
        segments.append({"language": current_script, "text": segment_text})

    return segments


def segment_contains_named_vowel(text: str) -> bool:
    tokens = [token for token in re.split(r"\s+", (text or "").strip()) if token]
    meaningful_tokens = []
    for token in tokens:
        stripped = token.strip(TRAILING_PUNCTUATION)
        if not stripped:
            continue
        if stripped in STANDALONE_VOWEL_NAMES:
            continue
        meaningful_tokens.append(stripped)
    return bool(meaningful_tokens)


def english_segment_mentions_vowel(text: str, token: str) -> bool:
    hints = ENGLISH_VOWEL_LABEL_HINTS.get(token, ())
    lowered = (text or "").lower()
    return any(hint in lowered for hint in hints)


def normalize_hebrew_mixed_segment(
    text: str,
    *,
    previous_english: Optional[str],
    next_english: Optional[str],
) -> Optional[str]:
    raw_tokens = [token for token in re.split(r"\s+", (text or "").strip()) if token]
    if not raw_tokens:
        return None

    has_named_token = segment_contains_named_vowel(text)
    normalized_tokens: List[str] = []
    for token in raw_tokens:
        stripped = token.strip(TRAILING_PUNCTUATION)
        if not stripped:
            continue

        if stripped in STANDALONE_VOWEL_NAMES:
            if has_named_token:
                continue
            if english_segment_mentions_vowel(previous_english, stripped) or english_segment_mentions_vowel(next_english, stripped):
                continue
            normalized_tokens.append(STANDALONE_VOWEL_NAMES[stripped])
            continue

        if stripped == "יְיָ":
            normalized_tokens.append("אֲדֹנָי")
            continue

        if stripped in ISOLATED_HEBREW_AUDIO_OVERRIDES and len(raw_tokens) == 1:
            normalized_tokens.append(ISOLATED_HEBREW_AUDIO_OVERRIDES[stripped])
            continue

        normalized_tokens.append(token.strip())

    normalized_text = " ".join(token for token in normalized_tokens if token).strip()
    return normalized_text or None


def normalize_english_audio_text(text: Optional[str]) -> Optional[str]:
    normalized = (text or "").strip()
    if not normalized:
        return None

    for pattern, replacement in ENGLISH_AUDIO_TEXT_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def normalize_mixed_audio_segments(segments: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for index, segment in enumerate(segments):
        language = segment["language"]
        text = segment["text"].strip()
        if not text:
            continue

        if language == "he":
            previous_english = segments[index - 1]["text"] if index > 0 and segments[index - 1]["language"] == "en" else ""
            next_english = segments[index + 1]["text"] if index + 1 < len(segments) and segments[index + 1]["language"] == "en" else ""
            text = normalize_hebrew_mixed_segment(
                text,
                previous_english=previous_english,
                next_english=next_english,
            ) or ""
            if not text:
                continue
        else:
            text = normalize_english_audio_text(text) or ""
            if not text:
                continue

        if normalized and normalized[-1]["language"] == language:
            normalized[-1]["text"] = (normalized[-1]["text"] + " " + text).strip()
        else:
            normalized.append({"language": language, "text": text})

    return normalized


def ensure_mixed_audio_segments(
    *,
    item_id: str,
    text: Optional[str],
    hebrew_model: str,
    hebrew_voice_id: Optional[str],
    english_model: str,
    english_voice_id: Optional[str],
    api_key: Optional[str],
    output_format: str,
    allow_missing_audio: bool,
    manifest_entries: List[Dict],
    missing_items: List[Dict],
    revision: Optional[str],
) -> List[Dict]:
    segments = normalize_mixed_audio_segments(split_mixed_text_segments(text))
    output: List[Dict] = []

    for index, segment in enumerate(segments, start=1):
        language = segment["language"]
        segment_text = segment["text"]
        if language == "he":
            url = ensure_audio(
                category="lines",
                language="he",
                language_code="he",
                item_id=f"{item_id}-mixed-he-{index:02d}",
                text=segment_text,
                model_id=hebrew_model,
                voice_id=hebrew_voice_id,
                voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=revision,
            )
        else:
            url = ensure_audio(
                category="lines",
                language="en",
                language_code="en",
                item_id=f"{item_id}-mixed-en-{index:02d}",
                text=segment_text,
                model_id=english_model,
                voice_id=hebrew_voice_id or english_voice_id,
                voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=revision,
            )

        output.append(
            {
                "language": language,
                "text": segment_text,
                "url": url,
            }
        )

    return output


def dot_sensitive_tokens(tokens: List[str]) -> List[str]:
    results: List[str] = []
    seen = set()
    for token in tokens:
        if any(marker in token for marker in DOT_SENSITIVE_MARKERS) or any(pattern in token for pattern in DOT_SENSITIVE_PATTERNS):
            if token not in seen:
                results.append(token)
                seen.add(token)
    return results


def current_spoken_words(line: Dict, words_by_id: Dict[str, Dict]) -> List[str]:
    spoken: List[str] = []
    for word_id in line.get("wordIds", []):
        word = words_by_id.get(word_id)
        if word and word.get("spokenText"):
            spoken.append(word["spokenText"])
    return spoken


def current_display_words(line: Dict, words_by_id: Dict[str, Dict]) -> List[str]:
    display_words = line.get("displayWords")
    if isinstance(display_words, list) and display_words:
        return list(display_words)

    output: List[str] = []
    for word_id in line.get("wordIds", []):
        word = words_by_id.get(word_id)
        if word and word.get("displayText"):
            output.append(word["displayText"])
    return output


def prose_grouping_override(line: Dict) -> str:
    value = str(line.get("spokenGrouping") or "auto").strip().lower()
    if value in {"auto", "single", "force_start", "continue"}:
        return value
    return "auto"


def prose_group_key(line: Dict) -> str:
    content_mode = line.get("contentMode", "other")
    if content_mode == "hebrew":
        return "hebrew"
    if content_mode in {"english", "mixed"}:
        return "latin"
    return content_mode


def starts_like_continuation(text: Optional[str]) -> bool:
    return bool(LEADING_CONTINUATION_RE.match((text or "").strip()))


def ends_with_strong_stop(text: Optional[str]) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return stripped[-1] in ".!?׃"


def looks_like_header_line(line: Dict) -> bool:
    text = (line.get("displayText") or "").strip()
    if not text:
        return False

    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in HEADER_PREFIXES):
        return True

    if ":" in text and len(text.split()) <= 4 and not starts_like_continuation(text):
        return True

    words = [word for word in re.findall(r"[A-Za-z'’-]+", text) if word]
    if words and len(words) <= 8 and all(TITLE_CASE_RE.match(word) for word in words):
        return True

    return False


def looks_like_standalone_example(line: Dict, words_by_id: Dict[str, Dict]) -> bool:
    override = prose_grouping_override(line)
    if override == "single":
        return True

    text = (line.get("displayText") or "").strip()
    display_words = current_display_words(line, words_by_id)
    content_mode = line.get("contentMode", "other")

    if content_mode == "hebrew" and 0 < len(display_words) <= 2:
        return True

    if content_mode == "mixed":
        mixed_segments = split_mixed_text_segments(line.get("mixedText"))
        if len(mixed_segments) <= 2 and len(text.split()) <= 4:
            return True

    standalone_token = text.split()[0] if text.split() else ""
    if standalone_token in STANDALONE_VOWEL_NAMES:
        return True

    return False


def is_groupable_prose_line(line: Dict, words_by_id: Dict[str, Dict]) -> bool:
    if line.get("status") != "verified":
        return False
    if line.get("hebrewPlaybackMode") == "sequence":
        return False
    if not (line.get("displayText") or "").strip():
        return False
    if prose_grouping_override(line) in {"single", "force_start", "continue"}:
        return True
    return line.get("contentMode") in {"english", "mixed", "hebrew"} and not looks_like_header_line(line)


def should_continue_spoken_block(previous_line: Dict, current_line: Dict, words_by_id: Dict[str, Dict]) -> bool:
    current_override = prose_grouping_override(current_line)
    previous_override = prose_grouping_override(previous_line)
    if current_override == "force_start" or previous_override == "single":
        return False
    if current_override == "continue":
        return True
    if current_line.get("sectionId") != previous_line.get("sectionId"):
        return False
    if looks_like_header_line(current_line) or looks_like_standalone_example(current_line, words_by_id):
        return False
    if ends_with_strong_stop(previous_line.get("displayText")):
        return False

    previous_key = prose_group_key(previous_line)
    current_key = prose_group_key(current_line)

    if previous_key == "hebrew" and current_key == "hebrew":
        return not looks_like_standalone_example(previous_line, words_by_id)

    if current_key == "latin" and starts_like_continuation(current_line.get("displayText")):
        return True

    if previous_key == "latin" and current_key == "latin":
        return True

    return False


def line_spoken_segments(line: Dict, words_by_id: Dict[str, Dict]) -> List[Dict[str, str]]:
    content_mode = line.get("contentMode", "other")

    if content_mode == "english":
        text = normalize_english_audio_text(line.get("englishText"))
        return [{"language": "en", "text": text}] if text else []

    if content_mode == "mixed":
        return normalize_mixed_audio_segments(split_mixed_text_segments(line.get("mixedText")))

    if content_mode == "hebrew":
        text = hebrew_line_text(line, words_by_id)
        return [{"language": "he", "text": text}] if text else []

    return []


def merge_block_segments(segments: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    for segment in segments:
        language = segment.get("language")
        text = (segment.get("text") or "").strip()
        if not language or not text:
            continue
        if merged and merged[-1]["language"] == language:
            merged[-1]["text"] = (merged[-1]["text"] + " " + text).strip()
        else:
            merged.append({"language": language, "text": text})
    return merged


def build_spoken_blocks(page: Dict, words_by_id: Dict[str, Dict]) -> List[Dict]:
    ordered_page_lines = ordered_lines(page)
    blocks: List[List[Dict]] = []
    current_block: List[Dict] = []
    explicit_index: Dict[str, List[Dict]] = {}

    for line in ordered_page_lines:
        explicit_block_id = str(line.get("spokenBlockId") or "").strip()
        if explicit_block_id:
            explicit_index.setdefault(explicit_block_id, []).append(line)
            continue

        if not is_groupable_prose_line(line, words_by_id):
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue

        if not current_block:
            current_block = [line]
            continue

        if should_continue_spoken_block(current_block[-1], line, words_by_id):
            current_block.append(line)
        else:
            blocks.append(current_block)
            current_block = [line]

    if current_block:
        blocks.append(current_block)

    for _, lines in sorted(explicit_index.items(), key=lambda item: min(line["order"] for line in item[1])):
        blocks.append(sorted(lines, key=lambda line: line["order"]))

    blocks = sorted(blocks, key=lambda block_lines: block_lines[0]["order"])

    spoken_blocks: List[Dict] = []
    for index, block_lines in enumerate(blocks, start=1):
        segments = merge_block_segments(
            [
                segment
                for line in block_lines
                for segment in line_spoken_segments(line, words_by_id)
            ]
        )
        if not segments:
            continue
        manual_override = any(
            prose_grouping_override(line) != "auto" or str(line.get("spokenBlockId") or "").strip()
            for line in block_lines
        )
        spoken_blocks.append(
            {
                "id": f"{page['id']}-block-{index:02d}",
                "page": page["page"],
                "sectionId": block_lines[0].get("sectionId") or "default",
                "order": block_lines[0]["order"],
                "blockLabel": f"Block {index}",
                "lineIds": [line["id"] for line in block_lines],
                "lineNumbers": [line["order"] for line in block_lines],
                "contentMode": "mixed" if len({segment["language"] for segment in segments}) > 1 else ("english" if segments[0]["language"] == "en" else "hebrew"),
                "displayText": " ".join((line.get("displayText") or "").strip() for line in block_lines if (line.get("displayText") or "").strip()),
                "summaryText": (block_lines[0].get("displayText") or "").strip(),
                "segments": segments,
                "manualOverride": manual_override,
            }
        )

    line_to_block = {}
    for block in spoken_blocks:
        line_count = len(block["lineIds"])
        for offset, line_id in enumerate(block["lineIds"]):
            if line_count == 1:
                role = "single"
            elif offset == 0:
                role = "start"
            elif offset == line_count - 1:
                role = "end"
            else:
                role = "continue"
            line_to_block[line_id] = (block["id"], block["blockLabel"], role)

    for line in ordered_page_lines:
        assignment = line_to_block.get(line["id"])
        if not assignment:
            continue
        line["spokenBlockId"] = assignment[0]
        line["spokenBlockLabel"] = assignment[1]
        line["spokenBlockRole"] = assignment[2]
        line["manualBlockOverride"] = any(
            block["id"] == assignment[0] and block.get("manualOverride")
            for block in spoken_blocks
        )

    return spoken_blocks


def build_spoken_block_audio(
    *,
    block: Dict,
    hebrew_model: str,
    hebrew_voice_id: Optional[str],
    english_model: str,
    english_voice_id: Optional[str],
    api_key: Optional[str],
    output_format: str,
    allow_missing_audio: bool,
    manifest_entries: List[Dict],
    missing_items: List[Dict],
    revision: Optional[str],
) -> Dict:
    segments = block.get("segments", [])
    if not segments:
        return {"urls": [], "gapMs": 0, "mode": "missing", "segments": []}

    if len(segments) == 1:
        segment = segments[0]
        language = segment["language"]
        text = segment["text"]
        if language == "en":
            url = ensure_audio(
                category="blocks",
                language="en",
                language_code="en",
                item_id=block["id"],
                text=text,
                model_id=english_model,
                voice_id=hebrew_voice_id or english_voice_id,
                voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=revision,
            )
            return {"urls": [url] if url else [], "gapMs": 0, "mode": "english_block", "segments": [{"language": "en", "text": text, "url": url}] if url else []}

        url = ensure_audio(
            category="blocks",
            language="he",
            language_code="he",
            item_id=block["id"],
            text=text,
            model_id=hebrew_model,
            voice_id=hebrew_voice_id,
            voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
            api_key=api_key,
            output_format=output_format,
            allow_missing_audio=allow_missing_audio,
            manifest_entries=manifest_entries,
            missing_items=missing_items,
            revision=revision,
        )
        return {"urls": [url] if url else [], "gapMs": 0, "mode": "hebrew_block", "segments": [{"language": "he", "text": text, "url": url}] if url else []}

    output_segments: List[Dict] = []
    for index, segment in enumerate(segments):
        language = segment["language"]
        text = segment["text"]
        if language == "en":
            url = ensure_audio(
                category="blocks",
                language="en",
                language_code="en",
                item_id=f"{block['id']}-segment-{index+1:02d}",
                text=text,
                model_id=english_model,
                voice_id=hebrew_voice_id or english_voice_id,
                voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=revision,
            )
        else:
            url = ensure_audio(
                category="blocks",
                language="he",
                language_code="he",
                item_id=f"{block['id']}-segment-{index+1:02d}",
                text=text,
                model_id=hebrew_model,
                voice_id=hebrew_voice_id,
                voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=revision,
            )
        output_segments.append({"language": language, "text": text, "url": url})

    urls = [segment["url"] for segment in output_segments if segment.get("url")]
    return {
        "urls": urls,
        "gapMs": DEFAULT_BLOCK_SEGMENT_GAP_MS if len(urls) > 1 else 0,
        "mode": "mixed_block_segments",
        "segments": output_segments,
    }


def qa_playback_for_line(line: Dict) -> Dict:
    if line.get("playback"):
        playback = line["playback"]
        return {
            "mode": line.get("currentAudioMode", "missing"),
            "urls": list(playback.get("urls", [])),
            "gapMs": playback.get("gapMs", 0),
            "segments": line.get("mixedSegments", []),
        }

    audio = line.get("audio", {})
    mixed_audio = audio.get("mixed", {}) if isinstance(audio.get("mixed"), dict) else {}
    mixed_segments = [segment for segment in mixed_audio.get("segments", []) if segment.get("url")]
    if mixed_segments:
        return {
            "mode": "mixed_segments",
            "urls": [segment["url"] for segment in mixed_segments],
            "gapMs": mixed_audio.get("gapMs", 0),
            "segments": mixed_segments,
        }

    if mixed_audio.get("line"):
        return {
            "mode": "mixed_line",
            "urls": [mixed_audio["line"]],
            "gapMs": 0,
            "segments": [],
        }

    if line.get("hebrewPlaybackMode") == "sequence" and line.get("hebrewAudioSequence"):
        return {
            "mode": "hebrew_sequence",
            "urls": list(line.get("hebrewAudioSequence", [])),
            "gapMs": sequence_gap_ms(line),
            "segments": [],
        }

    he_audio = audio.get("he", {}) if isinstance(audio.get("he"), dict) else {}
    if he_audio.get("line"):
        return {
            "mode": "hebrew_line",
            "urls": [he_audio["line"]],
            "gapMs": 0,
            "segments": [],
        }

    en_audio = audio.get("en", {}) if isinstance(audio.get("en"), dict) else {}
    if en_audio.get("line"):
        return {
            "mode": "english_line",
            "urls": [en_audio["line"]],
            "gapMs": 0,
            "segments": [],
        }

    return {
        "mode": "missing",
        "urls": [],
        "gapMs": 0,
        "segments": [],
    }


def general_sample_line_ids(pages: List[Dict]) -> List[str]:
    samples: List[str] = []
    page_ids = set(QA_PRIORITY_PAGES)
    if pages:
        stride = max(1, len(pages) // 8)
        for index in range(0, len(pages), stride):
            page_ids.add(pages[index]["page"])

    for page in pages:
        if page["page"] not in page_ids:
            continue
        for line in page.get("lines", []):
            playback = qa_playback_for_line(line)
            if playback["urls"]:
                samples.append(line["id"])
                break
    return samples


def build_qa_payload(site_payload: Dict) -> Dict:
    pages_out: List[Dict] = []
    mixed_line_ids: List[str] = []
    dot_sensitive_line_ids: List[str] = []
    drill_line_ids: List[str] = []

    for page in site_payload.get("pages", []):
        words_by_id = {word["id"]: word for word in page.get("words", [])}
        spoken_blocks_by_id = {block["id"]: block for block in page.get("spokenBlocks", [])}
        page_lines: List[Dict] = []
        for line in ordered_lines(page):
            display_words = current_display_words(line, words_by_id)
            spoken_words = current_spoken_words(line, words_by_id)
            risk_tokens = dot_sensitive_tokens(display_words)
            playback = qa_playback_for_line(line)
            spoken_block = spoken_blocks_by_id.get(line.get("spokenBlockId"))
            raw_mixed_segments = (
                (((line.get("audio") or {}).get("mixed") or {}).get("segments") or [])
                if isinstance(line.get("audio"), dict)
                else []
            )
            english_audio_text = normalize_english_audio_text(line.get("englishText"))
            word_playback = []
            for word_id in line.get("wordIds", []):
                word = words_by_id.get(word_id)
                if not word:
                    continue
                word_playback.append(
                    {
                        "id": word["id"],
                        "displayText": word.get("displayText", ""),
                        "spokenText": word.get("spokenText", ""),
                        "url": (((word.get("audio") or {}).get("he") or {}).get("word")),
                    }
                )
            is_mixed = bool(line.get("contentMode") == "mixed" or line.get("mixedText"))
            is_drill = bool(line.get("hebrewPlaybackMode") == "sequence" and line.get("wordIds"))
            if is_mixed:
                mixed_line_ids.append(line["id"])
            if risk_tokens:
                dot_sensitive_line_ids.append(line["id"])
            if is_drill:
                drill_line_ids.append(line["id"])

            page_lines.append(
                {
                    "id": line["id"],
                    "page": page["page"],
                    "pageId": page["id"],
                    "title": page["title"],
                    "lineNumber": line["order"],
                    "badgeLabel": line.get("badgeLabel") or line.get("label") or line["id"],
                    "displayText": line.get("displayText", ""),
                    "contentMode": line.get("contentMode", "other"),
                    "displayWords": display_words,
                    "currentSpokenWords": spoken_words,
                    "currentSpokenSummary": " | ".join(spoken_words),
                    "isMixedRisk": is_mixed,
                    "isDotSensitiveRisk": bool(risk_tokens),
                    "isDrill": is_drill,
                    "hasRegion": bool(line.get("region") or line.get("overlay")),
                    "riskTokens": risk_tokens,
                    "wordPlayback": word_playback,
                    "mixedSegments": playback["segments"],
                    "currentAudioMode": playback["mode"],
                    "playback": {
                        "urls": playback["urls"],
                        "gapMs": playback["gapMs"],
                    },
                    "spokenBlockId": line.get("spokenBlockId"),
                    "spokenBlockLabel": line.get("spokenBlockLabel", ""),
                    "spokenBlockRole": line.get("spokenBlockRole", ""),
                    "spokenBlockLineCount": len(spoken_block.get("lineIds", [])) if spoken_block else 0,
                    "manualBlockOverride": bool(line.get("manualBlockOverride")),
                    "spokenBlockPlayback": spoken_block.get("playback") if spoken_block else None,
                    "spokenBlockSummary": spoken_block.get("summaryText", "") if spoken_block else "",
                    "region": resolved_region(line),
                    "status": line.get("status"),
                    "reviewFingerprint": stable_hash(
                        {
                            "page": page["page"],
                            "audioRevision": page.get("audioRevision"),
                            "lineId": line["id"],
                            "displayText": line.get("displayText", ""),
                            "contentMode": line.get("contentMode", "other"),
                            "displayWords": display_words,
                            "spokenWords": spoken_words,
                            "englishText": line.get("englishText", ""),
                            "englishAudioText": english_audio_text or "",
                            "mixedText": line.get("mixedText", ""),
                            "spokenBlockId": line.get("spokenBlockId", ""),
                            "spokenBlockRole": line.get("spokenBlockRole", ""),
                            "spokenBlockDisplayText": spoken_block.get("displayText", "") if spoken_block else "",
                            "spokenBlockSegments": spoken_block.get("segments", []) if spoken_block else [],
                            "spokenBlockPlayback": spoken_block.get("playback", {}) if spoken_block else {},
                            "playbackMode": playback["mode"],
                            "playbackSegments": playback["segments"],
                            "rawMixedSegments": [
                                {
                                    "language": segment.get("language", ""),
                                    "text": segment.get("text", ""),
                                }
                                for segment in raw_mixed_segments
                            ],
                        }
                    ),
                }
            )

        pages_out.append(
            {
                "id": page["id"],
                "page": page["page"],
                "title": page["title"],
                "image": page["image"],
                "spokenBlocks": [
                    {
                        "id": block["id"],
                        "blockLabel": block.get("blockLabel", block["id"]),
                        "lineIds": list(block.get("lineIds", [])),
                        "lineNumbers": list(block.get("lineNumbers", [])),
                        "displayText": block.get("displayText", ""),
                        "summaryText": block.get("summaryText", ""),
                        "playback": dict(block.get("playback", {})),
                        "manualOverride": bool(block.get("manualOverride")),
                    }
                    for block in page.get("spokenBlocks", [])
                ],
                "lines": page_lines,
            }
        )

    return {
        "version": site_payload.get("version"),
        "generatedAt": site_payload.get("generatedAt"),
        "overview": {
            "pageCount": len(pages_out),
            "lineCount": sum(len(page["lines"]) for page in pages_out),
            "mixedRiskCount": len(mixed_line_ids),
            "dotSensitiveRiskCount": len(dot_sensitive_line_ids),
            "drillCount": len(drill_line_ids),
        },
        "criticalPass": {
            "priorityPages": [page["page"] for page in pages_out if page["page"] in QA_PRIORITY_PAGES],
            "mixedLineIds": mixed_line_ids,
            "dotSensitiveLineIds": dot_sensitive_line_ids,
            "drillArrowLineIds": drill_line_ids,
            "generalSampleLineIds": general_sample_line_ids(pages_out),
        },
        "pages": pages_out,
    }


def hebrew_line_text(line: Dict, words_by_id: Dict[str, Dict]) -> Optional[str]:
    word_ids = line.get("wordIds", [])
    if not word_ids:
        return None

    display_words = line.get("displayWords")
    use_display_words = isinstance(display_words, list) and len(display_words) == len(word_ids)

    parts: List[str] = []
    for index, word_id in enumerate(word_ids):
        word = words_by_id.get(word_id)
        if not word:
            return None

        spoken_text = (word.get("spokenText") or "").strip()
        if not spoken_text:
            return None

        if use_display_words:
            punctuation = trailing_punctuation(display_words[index])
            if punctuation and not spoken_text.endswith(punctuation):
                spoken_text += punctuation

        parts.append(spoken_text)

    return " ".join(parts)


def hebrew_playback_mode(line: Dict) -> str:
    return "sequence" if line.get("hebrewPlaybackMode") == "sequence" else "continuous"


def sequence_gap_ms(line: Dict) -> int:
    value = line.get("sequenceGapMs")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return DEFAULT_SEQUENCE_GAP_MS


def resolved_region(line: Dict) -> Optional[Dict]:
    region = line.get("region") or line.get("overlay")
    if not region:
        return None
    return dict(region)


def load_pillow_image():
    try:
        from PIL import Image
    except ImportError as exc:
        raise BuildError(
            "Pillow is required to generate line-strip images. "
            "Install it locally or let the GitHub Actions workflow build the site."
        ) from exc
    return Image


def padded_region_bounds(region: Dict) -> Tuple[float, float, float, float]:
    left = max(0.0, region["left"] - region.get("padLeft", 0.0))
    top = max(0.0, region["top"] - region.get("padTop", 0.0))
    right = min(100.0, region["left"] + region["width"] + region.get("padRight", 0.0))
    bottom = min(100.0, region["top"] + region["height"] + region.get("padBottom", 0.0))
    if right <= left or bottom <= top:
        raise BuildError(f"Invalid region bounds: {region}")
    return left, top, right, bottom


def region_bounds_in_pixels(region: Dict, width: int, height: int) -> Tuple[int, int, int, int]:
    left, top, right, bottom = padded_region_bounds(region)
    pixel_left = max(0, math.floor((left / 100.0) * width))
    pixel_top = max(0, math.floor((top / 100.0) * height))
    pixel_right = min(width, math.ceil((right / 100.0) * width))
    pixel_bottom = min(height, math.ceil((bottom / 100.0) * height))
    if pixel_right <= pixel_left:
        pixel_right = min(width, pixel_left + 1)
    if pixel_bottom <= pixel_top:
        pixel_bottom = min(height, pixel_top + 1)
    return pixel_left, pixel_top, pixel_right, pixel_bottom


def build_line_strip(*, page: Dict, line: Dict) -> Optional[str]:
    region = resolved_region(line)
    if not region:
        return None

    page_image_path = ROOT / page["image"]
    if not page_image_path.exists():
        raise BuildError(f"Page image for {page['id']} does not exist: {page_image_path}")

    Image = load_pillow_image()
    with Image.open(page_image_path) as image:
        pixel_bounds = region_bounds_in_pixels(region, image.width, image.height)
        crop = image.crop(pixel_bounds)
        fingerprint = stable_hash(
            {
                "page_id": page["id"],
                "line_id": line["id"],
                "image": page["image"],
                "region": region,
            }
        )
        relative_path = f"assets/line-strips/{page['id']}/{line['id']}-{fingerprint}.png"
        output_path = SITE_ROOT / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output_path, format="PNG")
    return relative_path


def build_site_data(source: Dict, *, allow_missing_audio: bool) -> Tuple[Dict, Dict]:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    hebrew_voice_id = os.getenv("ELEVENLABS_HEBREW_VOICE_ID")
    english_voice_id = os.getenv("ELEVENLABS_ENGLISH_VOICE_ID")
    hebrew_model = os.getenv("ELEVENLABS_HEBREW_MODEL", "eleven_v3")
    english_model = os.getenv("ELEVENLABS_ENGLISH_MODEL", "eleven_flash_v2_5")
    output_format = os.getenv("ELEVENLABS_OUTPUT_FORMAT", DEFAULT_OUTPUT_FORMAT)

    manifest_entries: List[Dict] = []
    missing_items: List[Dict] = []

    site_payload = {
        "version": source.get("version"),
        "generatedAt": os.getenv("HEBREW_READER_BUILD_TIMESTAMP", ""),
        "audioConfig": {
            "hebrewModel": hebrew_model,
            "englishModel": english_model,
            "outputFormat": output_format,
        },
        "pages": [],
    }

    for page in source.get("pages", []):
        page_audio_revision = page.get("audioRevision")
        page_out = {
            "id": page["id"],
            "page": page["page"],
            "title": page["title"],
            "status": page["status"],
            "image": page["image"],
            "englishText": page.get("englishText"),
            "notes": page.get("notes", []),
            "sections": [],
            "audio": {
                "en": {
                    "page": None
                }
            },
            "fullPlaybackGroups": [],
            "drillPlaybackGroups": [],
            "spokenBlocks": [],
            "lines": [],
            "words": [],
        }

        words_by_id: Dict[str, Dict] = {}
        for section in ordered_sections(page):
            section_out = clone_section(section)
            if section.get("status") == "verified" and section.get("playbackMode") == "single_block" and section.get("mixedText"):
                mixed_segments = ensure_mixed_audio_segments(
                    item_id=section["id"],
                    text=section.get("mixedText"),
                    hebrew_model=hebrew_model,
                    hebrew_voice_id=hebrew_voice_id,
                    english_model=english_model,
                    english_voice_id=english_voice_id,
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                    revision=page_audio_revision,
                )
                if mixed_segments:
                    section_out["audio"]["mixed"]["segments"] = mixed_segments
                    section_out["audio"]["mixed"]["gapMs"] = (
                        DEFAULT_MIXED_SEGMENT_GAP_MS if len(mixed_segments) > 1 else 0
                    )
                else:
                    section_out["audio"]["mixed"]["block"] = ensure_audio(
                        category="sections",
                        language="mixed",
                        language_code=None,
                        item_id=section["id"],
                        text=section.get("mixedText"),
                        model_id=hebrew_model,
                        voice_id=hebrew_voice_id,
                        voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                        api_key=api_key,
                        output_format=output_format,
                        allow_missing_audio=allow_missing_audio,
                        manifest_entries=manifest_entries,
                        missing_items=missing_items,
                        revision=page_audio_revision,
                    )
            page_out["sections"].append(section_out)

        for word in ordered_words(page):
            word_out = clone_word(word)
            if word.get("status") == "verified":
                word_out["audio"]["he"]["word"] = ensure_audio(
                    category="words",
                    language="he",
                    language_code="he",
                    item_id=word["id"],
                    text=word.get("spokenText"),
                    model_id=hebrew_model,
                    voice_id=hebrew_voice_id,
                    voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                    revision=page_audio_revision,
                )
            page_out["words"].append(word_out)
            words_by_id[word_out["id"]] = word_out

        for line in ordered_lines(page):
            line_out = clone_line(line)
            line_out["stripImage"] = build_line_strip(page=page, line=line_out)
            line_out["hebrewPlaybackMode"] = hebrew_playback_mode(line_out)
            if line_out["hebrewPlaybackMode"] == "sequence":
                line_out["sequenceGapMs"] = sequence_gap_ms(line_out)
            else:
                line_out.pop("sequenceGapMs", None)
            line_hebrew_text = hebrew_line_text(line, words_by_id)
            if (
                line.get("status") == "verified"
                and line_out["hebrewPlaybackMode"] != "sequence"
                and not line.get("mixedText")
                and line_hebrew_text
            ):
                line_out["audio"]["he"]["line"] = ensure_audio(
                    category="lines",
                    language="he",
                    language_code="he",
                    item_id=line["id"],
                    text=line_hebrew_text,
                    model_id=hebrew_model,
                    voice_id=hebrew_voice_id,
                    voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                    revision=page_audio_revision,
                )
            if line.get("status") == "verified" and line.get("mixedText"):
                mixed_segments = ensure_mixed_audio_segments(
                    item_id=line["id"],
                    text=line.get("mixedText"),
                    hebrew_model=hebrew_model,
                    hebrew_voice_id=hebrew_voice_id,
                    english_model=english_model,
                    english_voice_id=english_voice_id,
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                    revision=page_audio_revision,
                )
                if mixed_segments:
                    line_out["audio"]["mixed"]["segments"] = mixed_segments
                    line_out["audio"]["mixed"]["gapMs"] = (
                        DEFAULT_MIXED_SEGMENT_GAP_MS if len(mixed_segments) > 1 else 0
                    )
                else:
                    line_out["audio"]["mixed"]["line"] = ensure_audio(
                        category="lines",
                        language="mixed",
                        language_code=None,
                        item_id=line["id"],
                        text=line.get("mixedText"),
                        model_id=hebrew_model,
                        voice_id=hebrew_voice_id,
                        voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                        api_key=api_key,
                        output_format=output_format,
                        allow_missing_audio=allow_missing_audio,
                        manifest_entries=manifest_entries,
                        missing_items=missing_items,
                        revision=page_audio_revision,
                    )
            if line.get("status") == "verified" and line.get("englishText"):
                english_audio_text = normalize_english_audio_text(line.get("englishText"))
                line_out["audio"]["en"]["line"] = ensure_audio(
                    category="lines",
                    language="en",
                    language_code="en",
                    item_id=line["id"],
                    text=english_audio_text,
                    model_id=english_model,
                    voice_id=hebrew_voice_id or english_voice_id,
                    voice_secret_name="ELEVENLABS_HEBREW_VOICE_ID",
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                    revision=page_audio_revision,
                )

            missing_word_ids = [word_id for word_id in line.get("wordIds", []) if word_id not in words_by_id]
            if missing_word_ids:
                raise BuildError(f"Line {line['id']} references unknown word ids: {', '.join(missing_word_ids)}")

            line_sequence = [
                words_by_id[word_id]["audio"]["he"]["word"]
                for word_id in line.get("wordIds", [])
                if words_by_id[word_id]["audio"]["he"]["word"]
            ]
            line_out["hebrewAudioSequence"] = (
                line_sequence if len(line_sequence) == len(line.get("wordIds", [])) else []
            )
            if line_out["hebrewPlaybackMode"] == "sequence" and line_out["hebrewAudioSequence"]:
                page_out["drillPlaybackGroups"].append(
                    {
                        "label": line.get("badgeLabel") or line.get("label") or line["id"],
                        "lineId": line["id"],
                        "urls": list(line_out["hebrewAudioSequence"]),
                        "gapMs": sequence_gap_ms(line_out),
                    }
                )
            page_out["lines"].append(line_out)

        expected_page_word_ids = [
            word_id
            for line in page_out["lines"]
            if line.get("status") == "verified"
            for word_id in line.get("wordIds", [])
        ]
        page_sequence = [
            words_by_id[word_id]["audio"]["he"]["word"]
            for word_id in expected_page_word_ids
            if words_by_id[word_id]["audio"]["he"]["word"]
        ]
        page_out["hebrewAudioSequence"] = (
            page_sequence if len(page_sequence) == len(expected_page_word_ids) else []
        )

        spoken_blocks = build_spoken_blocks(page_out, words_by_id)
        for block in spoken_blocks:
            block_out = clone_spoken_block(block)
            block_playback = build_spoken_block_audio(
                block=block,
                hebrew_model=hebrew_model,
                hebrew_voice_id=hebrew_voice_id,
                english_model=english_model,
                english_voice_id=english_voice_id,
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
                revision=page_audio_revision,
            )
            block_out["segments"] = block_playback["segments"]
            block_out["playback"] = {
                "urls": block_playback["urls"],
                "gapMs": block_playback["gapMs"],
                "mode": block_playback["mode"],
            }
            page_out["spokenBlocks"].append(block_out)

        spoken_blocks_by_id = {block["id"]: block for block in page_out["spokenBlocks"]}
        for line in page_out["lines"]:
            block = spoken_blocks_by_id.get(line.get("spokenBlockId"))
            if not block:
                continue
            line["playback"] = {
                "urls": list((block.get("playback") or {}).get("urls", [])),
                "gapMs": (block.get("playback") or {}).get("gapMs", 0),
                "mode": (block.get("playback") or {}).get("mode", "missing"),
                "segments": list(block.get("segments", [])),
            }

        playback_items: List[Dict] = []
        for block in page_out["spokenBlocks"]:
            urls = list((block.get("playback") or {}).get("urls", []))
            if not urls:
                continue
            playback_items.append(
                {
                    "order": block.get("order", 0),
                    "group": {
                        "label": block.get("blockLabel") or block["id"],
                        "lineId": block.get("lineIds", [None])[0],
                        "spokenBlockId": block["id"],
                        "urls": urls,
                        "gapMs": (block.get("playback") or {}).get("gapMs", 0),
                    },
                }
            )

        for drill in page_out["drillPlaybackGroups"]:
            line = next((item for item in page_out["lines"] if item["id"] == drill.get("lineId")), None)
            playback_items.append(
                {
                    "order": line.get("order", 0) if line else 0,
                    "group": dict(drill),
                }
            )

        page_out["fullPlaybackGroups"] = [item["group"] for item in sorted(playback_items, key=lambda item: item["order"])]

        for section in page_out["sections"]:
            section_mixed_audio = section.get("audio", {}).get("mixed", {})
            section_segment_urls = [
                segment.get("url")
                for segment in section_mixed_audio.get("segments", [])
                if segment.get("url")
            ]
            if section.get("playbackMode") == "single_block" and (section_segment_urls or section_mixed_audio.get("block")):
                continue
        site_payload["pages"].append(page_out)

    manifest = {
        "version": source.get("version"),
        "generatedAssets": manifest_entries,
        "missingAssets": missing_items,
        "summary": {
            "generated": sum(1 for item in manifest_entries if item["status"] == "generated"),
            "reused": sum(1 for item in manifest_entries if item["status"] == "reused"),
            "missing": len(missing_items),
        },
    }
    return site_payload, manifest


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static Hebrew pronunciation site.")
    parser.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Build the site even if verified items do not have audio yet.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    copy_static_assets()

    source = load_json(SOURCE_TRANSCRIPT)
    site_payload, manifest = build_site_data(source, allow_missing_audio=args.allow_missing_audio)
    qa_payload = build_qa_payload(site_payload)

    write_json(SITE_DATA / "reader.json", site_payload)
    write_json(SITE_DATA / "qa.json", qa_payload)
    write_json(SITE_DATA / "audio-manifest.json", manifest)

    print(f"Built site data for {len(site_payload['pages'])} page(s).")
    print(
        "QA summary: "
        f"{qa_payload['overview']['mixedRiskCount']} mixed-risk lines, "
        f"{qa_payload['overview']['dotSensitiveRiskCount']} dot-sensitive lines, "
        f"{qa_payload['overview']['drillCount']} drill lines."
    )
    print(
        "Audio summary: "
        f"{manifest['summary']['generated']} generated, "
        f"{manifest['summary']['reused']} reused, "
        f"{manifest['summary']['missing']} missing."
    )
    if manifest["missingAssets"]:
        print("Missing audio assets:")
        for item in manifest["missingAssets"]:
            print(f"  - {item['id']} ({item['language']}/{item['category']})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
