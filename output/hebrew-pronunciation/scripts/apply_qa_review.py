#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply QA review bundle overrides to transcript.json.")
    parser.add_argument("review_bundle", help="Path to exported QA review JSON.")
    parser.add_argument(
        "--transcript",
        default="/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation/transcript.json",
        help="Transcript JSON to update.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output transcript path. Defaults to overwriting --transcript.",
    )
    parser.add_argument(
        "--issues-output",
        default="",
        help="Optional JSON path for unresolved issue notes.",
    )
    return parser.parse_args(list(argv))


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_line_index(transcript: Dict) -> Dict[str, Tuple[Dict, Dict]]:
    index: Dict[str, Tuple[Dict, Dict]] = {}
    for page in transcript.get("pages", []):
        for line in page.get("lines", []):
            index[line["id"]] = (page, line)
    return index


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    review_path = Path(args.review_bundle)
    transcript_path = Path(args.transcript)
    output_path = Path(args.output) if args.output else transcript_path

    review = load_json(review_path)
    transcript = load_json(transcript_path)
    line_index = build_line_index(transcript)

    applied = []
    skipped = []
    for override in review.get("regionOverrides", []):
        line_id = override.get("lineId")
        region = override.get("region")
        if not line_id or not region:
            skipped.append({"reason": "missing_line_or_region", "override": override})
            continue

        match = line_index.get(line_id)
        if not match:
            skipped.append({"reason": "unknown_line_id", "override": override})
            continue

        page, line = match
        line["region"] = region
        line["matchMode"] = "hybrid"
        applied.append(
            {
                "page": page["page"],
                "lineId": line_id,
                "lineNumber": line.get("order"),
                "badgeLabel": line.get("badgeLabel"),
            }
        )

    write_json(output_path, transcript)

    unresolved_issues: List[Dict] = list(review.get("issues", []))
    issue_summary = {
        "reviewBundle": str(review_path),
        "reviewerName": review.get("reviewerName"),
        "sessionNotes": review.get("sessionNotes"),
        "appliedRegionOverrides": applied,
        "skippedRegionOverrides": skipped,
        "unresolvedIssues": unresolved_issues,
    }

    if args.issues_output:
        write_json(Path(args.issues_output), issue_summary)
    else:
        print(json.dumps(issue_summary, ensure_ascii=False, indent=2))

    print(
        f"Applied {len(applied)} region override(s), skipped {len(skipped)}, "
        f"left {len(unresolved_issues)} issue note(s) for manual follow-up."
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
