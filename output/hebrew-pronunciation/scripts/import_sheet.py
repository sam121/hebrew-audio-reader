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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "transcript.json"
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


def has_hebrew(text: str) -> bool:
    return bool(HEBREW_RE.search(text))


def has_latin(text: str) -> bool:
    return bool(LATIN_RE.search(text))


def tokenize_hebrew_words(text: str) -> List[str]:
    return [part for part in WORD_SPLIT_RE.split(clean_text(text)) if has_hebrew(part)]


def normalize_word_for_speech(token: str, *, drill_line: bool) -> str:
    spoken = clean_text(token)
    spoken = DIVINE_NAME_RE.sub("אֲדֹנָי", spoken)
    spoken = spoken.replace("־", " ")
    if drill_line and spoken.startswith("וּ"):
        spoken = "א" + spoken
    return spoken


def normalize_line_for_speech(text: str) -> str:
    spoken = clean_text(text)
    spoken = DIVINE_NAME_RE.sub("אֲדֹנָי", spoken)
    return spoken


def build_sections(line_rows: List[Dict]) -> List[Dict]:
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
            "mixedText": normalize_line_for_speech(intro_text),
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


def build_page(page_number: int, page_rows: List[Dict], *, pdf_path: str, audio_revision: str) -> Dict:
    sections = build_sections(page_rows)
    assign_section_id(page_rows, sections)

    words: List[Dict] = []
    lines: List[Dict] = []
    word_order = 1

    for row in page_rows:
        line_id = f"p{page_number:02d}-line-{row['line_number']:03d}"
        tokens = tokenize_hebrew_words(row["line_content"])
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
                    "spokenText": normalize_word_for_speech(token, drill_line=row["is_drill"]),
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
            "displayText": row["line_content"],
            "contentMode": content_mode,
            "notes": row["notes"],
            "wordIds": word_ids,
            "displayWords": tokens,
        }

        if row["is_drill"] and word_ids:
            line["hebrewPlaybackMode"] = "sequence"
            line["sequenceGapMs"] = 220

        if content_mode == "english":
            line["englishText"] = row["line_content"]
        elif content_mode == "mixed":
            line["mixedText"] = normalize_line_for_speech(row["line_content"])

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


def build_transcript(rows: List[Dict], *, pdf_path: str, audio_revision: str) -> Dict:
    pages_by_number: Dict[int, List[Dict]] = defaultdict(list)
    for row in rows:
        pages_by_number[row["page"]].append(row)

    pages = [
        build_page(page_number, sorted(page_rows, key=lambda item: item["line_number"]), pdf_path=pdf_path, audio_revision=audio_revision)
        for page_number, page_rows in sorted(pages_by_number.items())
    ]

    return {
        "version": "2026-04-12",
        "pdfPath": pdf_path,
        "notes": [
            "Imported from the Google Sheet submission tab.",
            "Display text and generated audio text are sourced from the sheet export.",
            "Drill rows play as word sequences with a short gap between clips.",
        ],
        "pages": pages,
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
    payload = build_transcript(rows, pdf_path=args.pdf_path, audio_revision=args.audio_revision)
    write_json(Path(args.output), payload)
    print(f"Imported {len(payload['pages'])} pages and {len(rows)} sheet rows into {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
