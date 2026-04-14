#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.request import urlopen

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional in some local shells
    Image = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "transcript.json"
DEFAULT_SYNC_CONFIG_PATH = ROOT / "qa-sync-config.json"
DEFAULT_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/1JvDXB7bjEQV_wEO4YTUJJ-S6TXLt8VcqqClz8PetPzs/"
    "export?format=csv&gid=413834508"
)
DEFAULT_PDF_PATH = "/Users/samueltaylor/Downloads/Learn Hebrew Today (Adult Hebrew book) (1) (1).pdf"
DEFAULT_AUDIO_REVISION = "2026-04-12-sheet-import-v1"
HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
LATIN_RE = re.compile(r"[A-Za-z]")
DRILL_RE = re.compile(r"^\s*(\d+)\.\s*")
WORD_SPLIT_RE = re.compile(r"\s+")
INVISIBLE_RE = re.compile(r"[\u200e\u200f\ufeff]")
DIVINE_NAME_RE = re.compile(r"(יְיָ|יְהוָה|יהוה)")
ISOLATED_SHEVA_RE = re.compile(r"^([א-ת])(\u05bc)?\u05b0$")
TRAILING_ENGLISH_AFTER_COLON_RE = re.compile(
    r"^\s*(?P<before>[\u0590-\u05FF\s.,!?\"'״׳()=\-־]+?)\s*:\s*(?P<english>[A-Za-z][^:]*)\s*$"
)
STANDALONE_VOWEL_SPOKEN_FORMS = {
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
REGION_DETECTION_CANDIDATES = [
    {"bottom": 0.88, "row_threshold": 8, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.88, "row_threshold": 10, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.9, "row_threshold": 8, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.9, "row_threshold": 10, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.9, "row_threshold": 12, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.9, "row_threshold": 15, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.92, "row_threshold": 8, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.92, "row_threshold": 10, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
    {"bottom": 0.94, "row_threshold": 8, "merge_gap": 4, "dark_threshold": 170, "min_height": 4},
]
SELECTIVE_UPDATE_STATUSES = {"bad", "needs_regen"}


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import the public Hebrew sheet into transcript.json.")
    parser.add_argument("--sheet-csv-url", default=DEFAULT_SHEET_CSV_URL)
    parser.add_argument(
        "--input-csv",
        default="",
        help="Optional local CSV path or '-' to read CSV content from stdin.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--pdf-path", default=DEFAULT_PDF_PATH)
    parser.add_argument("--audio-revision", default=DEFAULT_AUDIO_REVISION)
    parser.add_argument(
        "--review-sync-url",
        default="",
        help="Optional QA review backup endpoint. If omitted, qa-sync-config.json is used when available.",
    )
    parser.add_argument(
        "--force-all-lines",
        action="store_true",
        help="Import all sheet lines even if reviewed good lines exist in the QA backup.",
    )
    return parser.parse_args(list(argv))


def fetch_csv(url: str) -> str:
    with urlopen(url, timeout=120) as response:
        return response.read().decode("utf-8-sig")


def load_csv_text(args: argparse.Namespace) -> str:
    if args.input_csv == "-":
        return sys.stdin.read()
    if args.input_csv:
        return Path(args.input_csv).read_text(encoding="utf-8-sig")
    return fetch_csv(args.sheet_csv_url)


def clean_text(text: str) -> str:
    return INVISIBLE_RE.sub("", (text or "")).strip()


def reorder_mixed_display_text(text: str) -> str:
    cleaned = clean_text(text)
    if not (has_hebrew(cleaned) and has_latin(cleaned)):
        return cleaned

    match = TRAILING_ENGLISH_AFTER_COLON_RE.match(cleaned)
    if match:
        before = clean_text(match.group("before"))
        english = clean_text(match.group("english"))
        if before and english:
            return f"{english}: {before}"

    return cleaned


def has_hebrew(text: str) -> bool:
    return bool(HEBREW_RE.search(text))


def has_latin(text: str) -> bool:
    return bool(LATIN_RE.search(text))


def tokenize_hebrew_words(text: str) -> List[str]:
    return [part for part in WORD_SPLIT_RE.split(clean_text(text)) if has_hebrew(part)]


def replace_vet_with_vav(text: str) -> str:
    characters = list(text)
    output: List[str] = []
    index = 0
    while index < len(characters):
        character = characters[index]
        if character == "ב":
            look_ahead = index + 1
            has_dagesh = False
            while look_ahead < len(characters):
                next_char = characters[look_ahead]
                if "\u0590" <= next_char <= "\u05FF" and not ("\u0591" <= next_char <= "\u05C7"):
                    break
                if next_char == "ּ":
                    has_dagesh = True
                look_ahead += 1
            output.append("ב" if has_dagesh else "ו")
        else:
            output.append(character)
        index += 1
    return "".join(output)


def infer_page_context(page_rows: List[Dict]) -> Dict:
    has_vet_lesson = any(" vet" in row["line_content"].lower() for row in page_rows)
    has_sheva_lesson = any("sheva" in row["line_content"].lower() for row in page_rows)
    return {
        "vet_lesson": has_vet_lesson,
        "sheva_lesson": has_sheva_lesson,
    }


def apply_page_pronunciation_rules(text: str, *, page_context: Dict) -> str:
    spoken = text
    if page_context.get("vet_lesson"):
        spoken = replace_vet_with_vav(spoken)
    return spoken


def normalize_word_for_speech(token: str, *, drill_line: bool, page_context: Dict) -> str:
    spoken = clean_text(token)
    spoken = STANDALONE_VOWEL_SPOKEN_FORMS.get(spoken, spoken)
    spoken = DIVINE_NAME_RE.sub("אֲדֹנָי", spoken)
    spoken = spoken.replace("־", " ")
    spoken = apply_page_pronunciation_rules(spoken, page_context=page_context)
    if page_context.get("sheva_lesson"):
        sheva_match = ISOLATED_SHEVA_RE.match(spoken)
        if sheva_match:
            letter, dagesh = sheva_match.groups()
            spoken = letter + (dagesh or "") + "ִ"
    if drill_line and spoken.startswith("וּ"):
        spoken = "א" + spoken
    return spoken


def normalize_line_for_speech(text: str, *, page_context: Dict) -> str:
    spoken = clean_text(text)
    spoken = DIVINE_NAME_RE.sub("אֲדֹנָי", spoken)
    spoken = apply_page_pronunciation_rules(spoken, page_context=page_context)
    return spoken


def build_sections(line_rows: List[Dict], *, page_context: Dict) -> List[Dict]:
    first_drill_index: Optional[int] = None
    for index, row in enumerate(line_rows):
        if row["is_drill"]:
            first_drill_index = index
            break

    if first_drill_index is None or first_drill_index == 0:
        return [
            {
                "id": "main",
                "order": 1,
                "title": "Page",
                "playbackMode": "per_line",
                "matchMode": "none",
                "status": "verified",
            }
        ]

    intro_text = " ".join(row["line_content"] for row in line_rows[:first_drill_index] if row["line_content"].strip())
    return [
        {
            "id": "intro",
            "order": 1,
            "title": "Intro section",
            "playbackMode": "single_block",
            "playbackLabel": "Play intro section",
            "matchMode": "none",
            "status": "verified",
            "mixedText": normalize_line_for_speech(intro_text, page_context=page_context),
        },
        {
            "id": "exercise",
            "order": 2,
            "title": "Exercise section",
            "playbackMode": "per_line",
            "matchMode": "none",
            "status": "verified",
        },
    ]


def assign_section_id(line_rows: List[Dict], sections: List[Dict]) -> None:
    if len(sections) == 1:
        for row in line_rows:
            row["sectionId"] = sections[0]["id"]
        return

    first_drill_index = next(index for index, row in enumerate(line_rows) if row["is_drill"])
    for index, row in enumerate(line_rows):
        row["sectionId"] = "intro" if index < first_drill_index else "exercise"


def page_title(page_rows: List[Dict], page_number: int) -> str:
    for row in page_rows:
        content = row["line_content"].strip()
        if content:
            return content
    return f"Page {page_number}"


def page_image_path(page_number: int) -> Path:
    return ROOT / "pages" / f"page-{page_number:03d}.png"


def load_existing_transcript(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def deep_clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_default_review_sync_url() -> str:
    if not DEFAULT_SYNC_CONFIG_PATH.exists():
        return ""
    try:
        payload = json.loads(DEFAULT_SYNC_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if not payload.get("enabled"):
        return ""
    return str(payload.get("endpoint") or "").strip()


def load_remote_review_state(review_sync_url: str) -> Dict[str, Dict]:
    if not review_sync_url:
        return {}
    try:
        with urlopen(review_sync_url, timeout=120) as response:
            payload = json.load(response)
    except Exception:
        return {}

    line_reviews = payload.get("lineReviews", []) if isinstance(payload, dict) else []
    review_state: Dict[str, Dict] = {}
    for review in line_reviews:
        line_id = str(review.get("lineId") or "").strip()
        if not line_id:
            continue
        review_state[line_id] = {
            "status": str(review.get("status") or "pending").strip() or "pending",
            "category": str(review.get("category") or "").strip(),
            "note": str(review.get("note") or "").strip(),
        }
    return review_state


def renumber_page_words(page_number: int, lines: List[Dict], words_by_line_id: Dict[str, List[Dict]]) -> List[Dict]:
    words: List[Dict] = []
    next_order = 1
    for line in lines:
        selected_words = [deep_clone(word) for word in words_by_line_id.get(line["id"], [])]
        line["wordIds"] = []
        line["displayWords"] = [word.get("displayText", "") for word in selected_words]
        for word in selected_words:
            word_id = f"p{page_number:02d}-word-{next_order:03d}"
            word["id"] = word_id
            word["page"] = page_number
            word["lineId"] = line["id"]
            word["order"] = next_order
            words.append(word)
            line["wordIds"].append(word_id)
            next_order += 1
    return words


def merged_page_title(lines: List[Dict], fallback: str) -> str:
    for line in lines:
        content = str(line.get("displayText") or "").strip()
        if content:
            return content
    return fallback


def merge_page_with_review_filter(
    new_page: Dict,
    existing_page: Optional[Dict],
    review_state: Dict[str, Dict],
    *,
    audio_revision: str,
    force_all_lines: bool,
) -> Dict:
    if not existing_page or force_all_lines or not review_state:
        page = deep_clone(new_page)
        if existing_page and not force_all_lines:
            page["audioRevision"] = existing_page.get("audioRevision") or audio_revision
        return page

    existing_lines_by_id = {line.get("id"): line for line in existing_page.get("lines", []) if line.get("id")}
    existing_words_by_id = {word.get("id"): word for word in existing_page.get("words", []) if word.get("id")}
    new_words_by_id = {word.get("id"): word for word in new_page.get("words", []) if word.get("id")}

    selected_lines: List[Dict] = []
    selected_words_by_line_id: Dict[str, List[Dict]] = {}
    updated_line_count = 0

    for candidate_line in sorted(new_page.get("lines", []), key=lambda item: item["order"]):
        line_id = candidate_line["id"]
        existing_line = existing_lines_by_id.get(line_id)
        review = review_state.get(line_id, {})
        status = review.get("status", "pending")
        should_update = (
            force_all_lines
            or existing_line is None
            or status in SELECTIVE_UPDATE_STATUSES
        )

        if should_update:
            chosen_line = deep_clone(candidate_line)
            source_words = [deep_clone(new_words_by_id[word_id]) for word_id in candidate_line.get("wordIds", []) if word_id in new_words_by_id]
            updated_line_count += 1 if existing_line is not None else 0
        else:
            chosen_line = deep_clone(existing_line)
            source_words = [deep_clone(existing_words_by_id[word_id]) for word_id in existing_line.get("wordIds", []) if word_id in existing_words_by_id]

        selected_lines.append(chosen_line)
        selected_words_by_line_id[line_id] = source_words

    merged_page = deep_clone(existing_page)
    merged_page["id"] = new_page["id"]
    merged_page["page"] = new_page["page"]
    merged_page["sourcePdfPage"] = new_page.get("sourcePdfPage", existing_page.get("sourcePdfPage"))
    merged_page["image"] = new_page.get("image", existing_page.get("image"))
    merged_page["status"] = new_page.get("status", existing_page.get("status"))
    merged_page["title"] = merged_page_title(selected_lines, existing_page.get("title") or new_page.get("title", ""))
    merged_page["audioRevision"] = existing_page.get("audioRevision") or audio_revision

    existing_sections = deep_clone(existing_page.get("sections", []))
    existing_section_ids = {section.get("id") for section in existing_sections}
    if existing_sections and all((line.get("sectionId") in existing_section_ids) for line in selected_lines):
        merged_page["sections"] = existing_sections
    else:
        merged_page["sections"] = deep_clone(new_page.get("sections", []))

    merged_page["lines"] = selected_lines
    merged_page["words"] = renumber_page_words(merged_page["page"], merged_page["lines"], selected_words_by_line_id)
    merged_page["_updatedLineCount"] = updated_line_count
    return merged_page


def detect_candidate_bands(
    image: "Image.Image",
    *,
    bottom: float,
    row_threshold: int,
    merge_gap: int,
    dark_threshold: int,
    min_height: int,
    left_pct: float = 0.05,
    right_pct: float = 0.96,
    top_pct: float = 0.04,
) -> Dict:
    width, height = image.size
    left = int(width * left_pct)
    right = int(width * right_pct)
    top = int(height * top_pct)
    bottom_px = int(height * bottom)
    data = image.load()

    rows: List[int] = []
    for y in range(top, bottom_px):
        count = 0
        for x in range(left, right):
            if data[x, y] < dark_threshold:
                count += 1
        rows.append(count)

    bands: List[List[int]] = []
    start: Optional[int] = None
    for index, count in enumerate(rows):
        y = top + index
        if count > row_threshold and start is None:
            start = y
        elif count <= row_threshold and start is not None:
            bands.append([start, y - 1])
            start = None

    if start is not None:
        bands.append([start, bottom_px - 1])

    merged: List[List[int]] = []
    for start_px, end_px in bands:
        if merged and start_px - merged[-1][1] <= merge_gap:
            merged[-1][1] = end_px
        else:
            merged.append([start_px, end_px])

    filtered = [band for band in merged if (band[1] - band[0] + 1) >= min_height]
    max_height = max((band[1] - band[0] + 1) for band in filtered) if filtered else 9999
    return {
        "bands": filtered,
        "rows": rows,
        "top_px": top,
        "left_px": left,
        "right_px": right,
        "width": width,
        "height": height,
        "max_height": max_height,
    }


def merge_closest_bands(bands: List[List[int]], target_count: int) -> List[List[int]]:
    adjusted = [list(band) for band in bands]
    while len(adjusted) > target_count and len(adjusted) > 1:
        gaps = [adjusted[index + 1][0] - adjusted[index][1] for index in range(len(adjusted) - 1)]
        merge_index = min(range(len(gaps)), key=lambda index: gaps[index])
        adjusted[merge_index][1] = adjusted[merge_index + 1][1]
        adjusted.pop(merge_index + 1)
    return adjusted


def split_tallest_band(bands: List[List[int]], rows: List[int], top_px: int) -> bool:
    if not bands:
        return False

    tallest_index = max(range(len(bands)), key=lambda index: bands[index][1] - bands[index][0])
    start_px, end_px = bands[tallest_index]
    height = end_px - start_px + 1
    if height < 12:
        return False

    start_row = max(0, start_px - top_px)
    end_row = min(len(rows) - 1, end_px - top_px)
    band_rows = rows[start_row : end_row + 1]
    if len(band_rows) < 8:
        return False

    margin = max(2, len(band_rows) // 8)
    interior = band_rows[margin : len(band_rows) - margin]
    if len(interior) < 4:
        return False

    split_offset = min(range(len(interior)), key=lambda index: interior[index]) + margin
    split_px = start_px + split_offset
    if split_px <= start_px + 2 or split_px >= end_px - 2:
        split_px = start_px + (height // 2)
    if split_px <= start_px + 1 or split_px >= end_px - 1:
        return False

    bands[tallest_index : tallest_index + 1] = [[start_px, split_px - 1], [split_px + 1, end_px]]
    return True


def trim_footer_bands(bands: List[List[int]], page_height: int) -> List[List[int]]:
    adjusted = [list(band) for band in bands]
    if len(adjusted) < 2:
        return adjusted

    min_gap_px = max(110, int(page_height * 0.065))
    max_footer_height_px = max(18, int(page_height * 0.012))
    footer_start_px = int(page_height * 0.78)

    while len(adjusted) >= 2:
        last_start, last_end = adjusted[-1]
        prev_start, prev_end = adjusted[-2]
        last_height = last_end - last_start + 1
        gap = last_start - prev_end
        if last_start >= footer_start_px and last_height <= max_footer_height_px and gap >= min_gap_px:
            adjusted.pop()
            continue
        break

    return adjusted


def adjust_bands_to_count(bands: List[List[int]], rows: List[int], top_px: int, target_count: int) -> List[List[int]]:
    adjusted = [list(band) for band in bands]
    if len(adjusted) > target_count:
        adjusted = merge_closest_bands(adjusted, target_count)

    attempts = 0
    while len(adjusted) < target_count and attempts < target_count * 3:
        if not split_tallest_band(adjusted, rows, top_px):
            break
        attempts += 1

    return sorted(adjusted, key=lambda band: band[0])


def detect_text_bounds(
    image: "Image.Image",
    *,
    y1: int,
    y2: int,
    left: int,
    right: int,
    dark_threshold: int,
) -> Dict:
    data = image.load()
    band_height = y2 - y1 + 1
    row_counts: List[int] = []
    for y in range(y1, y2 + 1):
        count = 0
        for x in range(left, right):
            if data[x, y] < dark_threshold:
                count += 1
        row_counts.append(count)

    trim_rows = min(2, max(0, band_height // 4))
    candidate_rows = list(range(y1 + trim_rows, y2 - trim_rows + 1)) if (y2 - trim_rows) >= (y1 + trim_rows) else list(range(y1, y2 + 1))
    frame_row_threshold = int((right - left) * 0.55)
    sample_rows = [y for y in candidate_rows if row_counts[y - y1] < frame_row_threshold]
    if not sample_rows:
        sample_rows = candidate_rows

    columns: List[int] = []
    for x in range(left, right):
        count = 0
        for y in sample_rows:
            if data[x, y] < dark_threshold:
                count += 1
        columns.append(count)

    threshold = max(1, len(sample_rows) * 0.18)
    min_run_width = max(3, min(18, band_height // 2))
    edge_margin = max(8, int((right - left) * 0.015))

    runs: List[List[int]] = []
    start: Optional[int] = None
    for index, count in enumerate(columns):
        if count >= threshold and start is None:
            start = index
        elif count < threshold and start is not None:
            runs.append([start, index - 1])
            start = None
    if start is not None:
        runs.append([start, len(columns) - 1])

    filtered_runs: List[List[int]] = []
    for run_start, run_end in runs:
        run_width = run_end - run_start + 1
        near_left_edge = run_start <= edge_margin
        near_right_edge = run_end >= len(columns) - edge_margin - 1
        if (near_left_edge or near_right_edge) and run_width < min_run_width * 2:
            continue
        if run_width >= min_run_width:
            filtered_runs.append([run_start, run_end])

    if filtered_runs:
        min_x = left + filtered_runs[0][0]
        max_x = left + filtered_runs[-1][1]
    else:
        min_x = next((left + index for index, count in enumerate(columns) if count >= threshold), left)
        max_x = right - 1
        while max_x > min_x and columns[max_x - left] < threshold:
            max_x -= 1

    return {"left": min_x, "right": max(max_x, min_x)}


def pct(value: float, total: int) -> float:
    return round((value / total) * 100.0, 2)


def suggest_line_regions(page_number: int, page_rows: List[Dict], sections: List[Dict]) -> Dict[int, Dict]:
    if Image is None:
        return {}

    image_path = page_image_path(page_number)
    if not image_path.exists():
        return {}

    hidden_section_ids = {section["id"] for section in sections if section.get("playbackMode") == "single_block"}
    visible_rows = [row for row in page_rows if row.get("sectionId") not in hidden_section_ids]
    if not visible_rows:
        return {}

    expected_total = len(page_rows)
    best_candidate: Optional[Dict] = None

    with Image.open(image_path).convert("L") as image:
        for candidate in REGION_DETECTION_CANDIDATES:
            detected = detect_candidate_bands(image, **candidate)
            trimmed_bands = trim_footer_bands(detected["bands"], detected["height"])
            band_count = len(trimmed_bands)
            if band_count >= expected_total:
                score = (band_count - expected_total, detected["max_height"])
            else:
                score = (1000 + (expected_total - band_count), detected["max_height"])
            if best_candidate is None or score < best_candidate["score"]:
                best_candidate = {
                    "score": score,
                    "candidate": candidate,
                    "detected": detected,
                    "trimmed_bands": trimmed_bands,
                }

        if best_candidate is None:
            return {}

        detected = best_candidate["detected"]
        bands = adjust_bands_to_count(best_candidate["trimmed_bands"], detected["rows"], detected["top_px"], expected_total)
        hidden_row_count = len(page_rows) - len(visible_rows)
        bands = bands[hidden_row_count : hidden_row_count + len(visible_rows)]

        regions: Dict[int, Dict] = {}
        for row, band in zip(visible_rows, bands):
            y1, y2 = band
            bounds = detect_text_bounds(
                image,
                y1=y1,
                y2=y2,
                left=detected["left_px"],
                right=detected["right_px"],
                dark_threshold=best_candidate["candidate"]["dark_threshold"],
            )
            regions[row["line_number"]] = {
                "top": pct(y1, detected["height"]),
                "left": pct(bounds["left"], detected["width"]),
                "width": pct(bounds["right"] - bounds["left"] + 1, detected["width"]),
                "height": pct(y2 - y1 + 1, detected["height"]),
                "padTop": 0.45,
                "padRight": 0.8,
                "padBottom": 0.55,
                "padLeft": 1.2,
                "confidence": 0.92,
            }

        return regions


def build_page(
    page_number: int,
    page_rows: List[Dict],
    *,
    pdf_path: str,
    audio_revision: str,
    existing_page: Optional[Dict] = None,
) -> Dict:
    page_context = infer_page_context(page_rows)
    sections = build_sections(page_rows, page_context=page_context)
    assign_section_id(page_rows, sections)
    line_regions = suggest_line_regions(page_number, page_rows, sections)
    existing_lines = {
        line.get("id"): line
        for line in (existing_page or {}).get("lines", [])
        if line.get("id")
    }

    words: List[Dict] = []
    lines: List[Dict] = []
    word_order = 1

    for row in page_rows:
        line_id = f"p{page_number:02d}-line-{row['line_number']:03d}"
        display_text = reorder_mixed_display_text(row["line_content"])
        tokens = tokenize_hebrew_words(display_text)
        word_ids: List[str] = []

        for token in tokens:
            word_id = f"p{page_number:02d}-word-{word_order:03d}"
            word_ids.append(word_id)
            words.append(
                {
                    "id": word_id,
                    "page": page_number,
                    "lineId": line_id,
                    "order": word_order,
                    "displayText": token,
                    "spokenText": normalize_word_for_speech(token, drill_line=row["is_drill"], page_context=page_context),
                    "status": "verified",
                }
            )
            word_order += 1

        content_mode = (
            "mixed"
            if row["has_hebrew"] and row["has_latin"]
            else "hebrew"
            if row["has_hebrew"]
            else "english"
            if row["has_latin"]
            else "other"
        )

        line = {
            "id": line_id,
            "order": row["line_number"],
            "label": f"Page {page_number} line {row['line_number']}",
            "badgeLabel": f"Line {row['line_number']}",
            "sectionId": row["sectionId"],
            "status": "verified",
            "displayText": display_text,
            "contentMode": content_mode,
            "notes": row["notes"],
            "wordIds": word_ids,
            "displayWords": tokens,
        }

        existing_line = existing_lines.get(line_id, {})
        if "region" in existing_line:
            line["region"] = existing_line["region"]
        elif row["line_number"] in line_regions:
            line["region"] = line_regions[row["line_number"]]

        if "matchMode" in existing_line:
            line["matchMode"] = existing_line["matchMode"]
        elif "region" in line:
            line["matchMode"] = "hybrid"

        if row["is_drill"] and word_ids:
            line["hebrewPlaybackMode"] = "sequence"
            line["sequenceGapMs"] = 220

        if content_mode == "english":
            line["englishText"] = display_text
        elif content_mode == "mixed":
            line["mixedText"] = normalize_line_for_speech(display_text, page_context=page_context)

        lines.append(line)

    return {
        "id": f"page-{page_number:03d}",
        "page": page_number,
        "sourcePdfPage": page_number,
        "title": page_title(page_rows, page_number),
        "status": "verified",
        "audioRevision": audio_revision,
        "image": f"pages/page-{page_number:03d}.png",
        "notes": [],
        "sections": sections,
        "lines": lines,
        "words": words,
    }


def load_rows(csv_text: str) -> List[Dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: List[Dict] = []
    for raw in reader:
        page_value = clean_text(raw.get("page", ""))
        line_value = clean_text(raw.get("line", ""))
        if not page_value.isdigit() or not line_value.isdigit():
            continue

        line_content = clean_text(raw.get("line_content", ""))
        notes = [
            clean_text(raw.get("notes", "")),
            clean_text(raw.get("Error Check", "")),
            clean_text(raw.get("Second Check", "")),
        ]
        notes = [note for note in notes if note]

        rows.append(
            {
                "page": int(page_value),
                "line_number": int(line_value),
                "line_content": line_content,
                "notes": notes,
                "is_drill": bool(DRILL_RE.match(line_content)),
                "has_hebrew": has_hebrew(line_content),
                "has_latin": has_latin(line_content),
            }
        )
    return rows


def build_transcript(
    rows: List[Dict],
    *,
    pdf_path: str,
    audio_revision: str,
    existing_transcript: Optional[Dict] = None,
    review_state: Optional[Dict[str, Dict]] = None,
    force_all_lines: bool = False,
) -> Dict:
    pages_by_number: Dict[int, List[Dict]] = defaultdict(list)
    for row in rows:
        pages_by_number[row["page"]].append(row)
    existing_pages = {
        page.get("page"): page
        for page in (existing_transcript or {}).get("pages", [])
        if page.get("page") is not None
    }

    pages = []
    updated_line_count = 0
    for page_number, page_rows in sorted(pages_by_number.items()):
        new_page = build_page(
            page_number,
            sorted(page_rows, key=lambda item: item["line_number"]),
            pdf_path=pdf_path,
            audio_revision=audio_revision,
            existing_page=existing_pages.get(page_number),
        )
        merged_page = merge_page_with_review_filter(
            new_page,
            existing_pages.get(page_number),
            review_state or {},
            audio_revision=audio_revision,
            force_all_lines=force_all_lines,
        )
        updated_line_count += merged_page.pop("_updatedLineCount", 0)
        pages.append(merged_page)

    notes = [
        "Imported from the Google Sheet submission tab.",
        "Display text and generated audio text are sourced from the sheet export.",
        "Drill rows play as word sequences with a short gap between clips.",
    ]
    if review_state and not force_all_lines:
        notes.append("Good QA-reviewed lines are preserved during sheet refreshes; only bad / needs-regeneration lines are updated.")

    return {
        "version": "2026-04-12",
        "pdfPath": pdf_path,
        "notes": notes,
        "pages": pages,
        "importSummary": {
            "pageCount": len(pages),
            "rowCount": len(rows),
            "reviewAware": bool(review_state) and not force_all_lines,
            "updatedReviewedLineCount": updated_line_count,
        },
    }


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    csv_text = load_csv_text(args)
    rows = load_rows(csv_text)
    output_path = Path(args.output)
    existing_transcript = load_existing_transcript(output_path)
    review_sync_url = (args.review_sync_url or load_default_review_sync_url()).strip()
    review_state = {} if args.force_all_lines else load_remote_review_state(review_sync_url)
    payload = build_transcript(
        rows,
        pdf_path=args.pdf_path,
        audio_revision=args.audio_revision,
        existing_transcript=existing_transcript,
        review_state=review_state,
        force_all_lines=args.force_all_lines,
    )
    write_json(output_path, payload)
    summary = payload.get("importSummary", {})
    review_note = ""
    if summary.get("reviewAware"):
        review_note = f" Preserved reviewed good lines; updated {summary.get('updatedReviewedLineCount', 0)} previously reviewed bad/needs-regeneration line(s)."
    elif args.force_all_lines:
        review_note = " Forced full-line refresh."
    print(f"Imported {len(payload['pages'])} pages and {len(rows)} sheet rows into {args.output}.{review_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
