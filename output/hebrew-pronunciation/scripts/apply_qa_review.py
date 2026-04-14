#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a contractor review bundle from qa.html.")
    parser.add_argument("review_bundle", help="Path to exported contractor review JSON.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON path for the summarized output. Prints to stdout if omitted.",
    )
    return parser.parse_args(list(argv))


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalized_line_review(review: Dict) -> Dict:
    return {
        "page": review.get("page"),
        "lineId": review.get("lineId"),
        "lineNumber": review.get("lineNumber"),
        "anchorY": review.get("anchorY"),
        "status": review.get("status", "pending"),
        "category": review.get("category", ""),
        "note": (review.get("note") or "").strip(),
    }


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    review_path = Path(args.review_bundle)
    bundle = load_json(review_path)

    line_reviews: List[Dict] = [
        normalized_line_review(review)
        for review in bundle.get("lineReviews", [])
    ]

    anchors = [
        {
            "page": review["page"],
            "lineId": review["lineId"],
            "lineNumber": review["lineNumber"],
            "anchorY": review["anchorY"],
        }
        for review in line_reviews
        if isinstance(review.get("anchorY"), (int, float))
    ]

    needs_regen = [review for review in line_reviews if review["status"] == "needs_regen"]
    bad_lines = [review for review in line_reviews if review["status"] == "bad"]
    good_lines = [review for review in line_reviews if review["status"] == "good"]
    pending_lines = [review for review in line_reviews if review["status"] == "pending"]

    summary = {
        "reviewBundle": str(review_path),
        "reviewerName": bundle.get("reviewerName", ""),
        "sessionNotes": bundle.get("sessionNotes", ""),
        "createdAt": bundle.get("createdAt"),
        "updatedAt": bundle.get("updatedAt"),
        "pageSignOffs": bundle.get("pageSignOffs", {}),
        "summary": {
            "lineCount": len(line_reviews),
            "anchorCount": len(anchors),
            "goodCount": len(good_lines),
            "badCount": len(bad_lines),
            "needsRegenCount": len(needs_regen),
            "pendingCount": len(pending_lines),
        },
        "lineAnchors": anchors,
        "needsRegen": needs_regen,
        "manualFollowUp": bad_lines,
        "pending": pending_lines,
        "good": good_lines,
    }

    if args.output:
        write_json(Path(args.output), summary)
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    print(
        f"Processed {len(line_reviews)} line review(s): "
        f"{len(good_lines)} good, {len(bad_lines)} bad, "
        f"{len(needs_regen)} need regeneration, {len(pending_lines)} pending."
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
