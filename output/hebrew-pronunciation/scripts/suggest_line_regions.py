#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from PIL import Image


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Suggest line regions from a scanned reader page using image bands."
    )
    parser.add_argument("image", help="Path to a page PNG.")
    parser.add_argument("--top", type=float, default=0.30, help="Top scan fraction to inspect.")
    parser.add_argument("--bottom", type=float, default=0.85, help="Bottom scan fraction to inspect.")
    parser.add_argument("--left", type=float, default=0.08, help="Left scan fraction to inspect.")
    parser.add_argument("--right", type=float, default=0.95, help="Right scan fraction to inspect.")
    parser.add_argument("--row-threshold", type=int, default=20, help="Minimum dark pixels per row.")
    parser.add_argument("--col-threshold", type=int, default=2, help="Minimum dark pixels per column.")
    parser.add_argument("--merge-gap", type=int, default=30, help="Merge bands separated by this many pixels or less.")
    parser.add_argument("--skip-leading-bands", type=int, default=0, help="Skip heading/helper bands before the exercise rows.")
    return parser.parse_args(argv)


def merge_intervals(intervals: List[List[int]], gap: int) -> List[List[int]]:
    merged: List[List[int]] = []
    for start, end in intervals:
        if not merged or start - merged[-1][1] > gap:
            merged.append([start, end])
        else:
            merged[-1][1] = end
    return merged


def detect_row_bands(
    image: Image.Image,
    *,
    left: int,
    right: int,
    top: int,
    bottom: int,
    row_threshold: int,
    merge_gap: int,
) -> List[Tuple[int, int]]:
    data = image.load()
    rows: List[int] = []
    for y in range(top, bottom):
        count = 0
        for x in range(left, right):
            if data[x, y] < 170:
                count += 1
        rows.append(count)

    raw_bands: List[List[int]] = []
    start = None
    for index, count in enumerate(rows):
        y = top + index
        if count > row_threshold and start is None:
            start = y
        elif count <= row_threshold and start is not None:
            raw_bands.append([start, y - 1])
            start = None

    if start is not None:
        raw_bands.append([start, bottom - 1])

    return [(start, end) for start, end in merge_intervals(raw_bands, merge_gap)]


def detect_text_bounds(
    image: Image.Image,
    *,
    y1: int,
    y2: int,
    left: int,
    right: int,
    col_threshold: int,
) -> Tuple[int, int]:
    data = image.load()
    column_counts: List[int] = []
    for x in range(left, right):
        count = 0
        for y in range(y1, y2 + 1):
            if data[x, y] < 170:
                count += 1
        column_counts.append(count)

    clusters: List[Tuple[int, int]] = []
    start = None
    for index, count in enumerate(column_counts):
        x = left + index
        if count > col_threshold and start is None:
            start = x
        elif count <= col_threshold and start is not None:
            clusters.append((start, x - 1))
            start = None

    if start is not None:
        clusters.append((start, right - 1))

    filtered: List[Tuple[int, int]] = []
    for cluster_left, cluster_right in clusters:
        width = cluster_right - cluster_left + 1
        if cluster_left < left + 20 and width < 20:
            continue
        if cluster_left > right - 220 and width < 80:
            continue
        filtered.append((cluster_left, cluster_right))

    if not filtered:
        filtered = clusters

    return filtered[0][0], filtered[-1][1]


def pct(value: float, total: int) -> float:
    return round((value / total) * 100.0, 2)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    image_path = Path(args.image).expanduser().resolve()
    with Image.open(image_path).convert("L") as image:
        width, height = image.size
        left = int(width * args.left)
        right = int(width * args.right)
        top = int(height * args.top)
        bottom = int(height * args.bottom)

        bands = detect_row_bands(
            image,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            row_threshold=args.row_threshold,
            merge_gap=args.merge_gap,
        )

        exercise_bands = bands[args.skip_leading_bands :]
        suggestions = []
        for index, (y1, y2) in enumerate(exercise_bands, start=1):
            x1, x2 = detect_text_bounds(
                image,
                y1=y1,
                y2=y2,
                left=left,
                right=right,
                col_threshold=args.col_threshold,
            )
            suggestions.append(
                {
                    "line": index,
                    "region": {
                        "top": pct(y1, height),
                        "left": pct(x1, width),
                        "width": pct(x2 - x1 + 1, width),
                        "height": pct(y2 - y1 + 1, height),
                        "padTop": 0.35,
                        "padRight": 0.8,
                        "padBottom": 0.45,
                        "padLeft": 0.95,
                        "confidence": 0.97,
                    },
                    "pixels": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                }
            )

    print(json.dumps({"image": str(image_path), "suggestions": suggestions}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(__import__("sys").argv[1:])))
