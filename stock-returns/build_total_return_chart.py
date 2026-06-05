import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BRK_PATH = ROOT / "brk_a_yahoo_daily.json"
ROP_PATH = ROOT / "rop_yahoo_daily.json"
SPY_PATH = ROOT / "spy_yahoo_daily.json"
ACWI_PATH = ROOT / "acwi_yahoo_daily.json"
CSV_PATH = ROOT / "berkshire_roper_total_return.csv"
HTML_PATH = ROOT / "berkshire_roper_total_return.html"
INDEX_PATH = ROOT / "index.html"
SITE_DIR = ROOT / "site"
SITE_INDEX_PATH = SITE_DIR / "index.html"

BENCHMARK_DEFS = {
    "spy": {
        "label": "S&P 500 (SPY)",
        "shortLabel": "SPY",
        "detail": "S&P 500 ETF proxy",
        "color": "#d6b98d",
        "dash": "8 7",
        "path": SPY_PATH,
    },
    "acwi": {
        "label": "World Equity Proxy (ACWI)",
        "shortLabel": "ACWI",
        "detail": "Broad global equity ETF proxy",
        "color": "#a8c1d6",
        "dash": "6 6",
        "path": ACWI_PATH,
    },
}

ROPER_EVENT_DEFS = [
    {
        "id": "1992-public-return",
        "date": "1992-02-13",
        "label": "Public relist",
        "title": "Roper returns to the public market",
        "detail": (
            "Marks the start of the public comparison record and Derrick Key's first restructuring phase."
        ),
    },
    {
        "id": "2001-jellison",
        "date": "2001-01-02",
        "label": "Jellison takes over",
        "title": "Brian Jellison becomes CEO and resets the playbook",
        "detail": (
            "Jellison begins the CRI and capital-light acquisition era."
        ),
    },
    {
        "id": "2002-neptune",
        "date": "2002-06-03",
        "label": "Neptune deal",
        "title": "Neptune acquisition validates the first big strategic bet",
        "detail": (
            "The first major deal that validated the new capital-allocation strategy."
        ),
    },
    {
        "id": "2003-transcore",
        "date": "2003-06-02",
        "label": "TransCore",
        "title": "TransCore gives Roper an early gateway into software economics",
        "detail": (
            "TransCore introduced software-like network economics through Dial-A-Truck."
        ),
    },
    {
        "id": "2008-cbord",
        "date": "2008-06-02",
        "label": "CBORD",
        "title": "CBORD becomes the first clear pure-software milestone",
        "detail": (
            "CBORD made the software pivot clearly structural rather than experimental."
        ),
    },
    {
        "id": "2012-sunquest",
        "date": "2012-06-01",
        "label": "Sunquest",
        "title": "Sunquest shows that not every vertical-software niche behaves the same",
        "detail": (
            "A rare strategic miss that exposed platform-bundling risk in healthcare software."
        ),
    },
    {
        "id": "2015-clinisys",
        "date": "2015-06-01",
        "label": "Clinisys",
        "title": "Clinisys becomes the platform used to absorb and repair the Sunquest issue",
        "detail": (
            "Clinisys became the platform used to absorb and repair the Sunquest issue."
        ),
    },
    {
        "id": "2018-handoff",
        "date": "2018-09-04",
        "label": "CEO handoff",
        "title": "Jellison steps down and the operating model faces succession risk",
        "detail": (
            "The succession handoff tested whether the operating model could outlast its architect."
        ),
    },
    {
        "id": "2022-divestitures",
        "date": "2022-06-01",
        "label": "2022 reset",
        "title": "Major divestitures push the portfolio decisively toward software",
        "detail": (
            "Major divestitures pushed the portfolio decisively toward software."
        ),
    },
]


@dataclass(frozen=True)
class Point:
    date: datetime
    close: float
    adjusted_close: float


def load_series(path: Path) -> list[Point]:
    payload = json.loads(path.read_text())
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote_close = result["indicators"]["quote"][0]["close"]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]

    points: list[Point] = []
    for timestamp, close_value, adjusted_value in zip(timestamps, quote_close, adjusted):
        if close_value is None or adjusted_value is None:
            continue
        points.append(
            Point(
                date=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                close=float(close_value),
                adjusted_close=float(adjusted_value),
            )
        )
    return points


def benchmark_payload(points: list[Point]) -> dict[str, object]:
    by_day = {point.date.date().isoformat(): point for point in points}
    first = points[0]
    return {
        "by_day": by_day,
        "start_date": first.date.date().isoformat(),
        "start_close": first.close,
        "start_adj": first.adjusted_close,
    }


def align_series(
    brk_points: list[Point],
    rop_points: list[Point],
    benchmark_points: dict[str, list[Point]],
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    brk_by_day = {point.date.date().isoformat(): point for point in brk_points}
    rop_by_day = {point.date.date().isoformat(): point for point in rop_points}

    common_days = sorted(set(brk_by_day) & set(rop_by_day))
    start_day = common_days[0]
    brk_start_adj = brk_by_day[start_day].adjusted_close
    rop_start_adj = rop_by_day[start_day].adjusted_close
    brk_start_close = brk_by_day[start_day].close
    rop_start_close = rop_by_day[start_day].close

    benchmark_meta = {
        key: benchmark_payload(points) for key, points in benchmark_points.items()
    }

    rows: list[dict[str, object]] = []
    for day in common_days:
        brk_point = brk_by_day[day]
        rop_point = rop_by_day[day]

        brk_total_growth = brk_point.adjusted_close / brk_start_adj
        rop_total_growth = rop_point.adjusted_close / rop_start_adj
        brk_price_growth = brk_point.close / brk_start_close
        rop_price_growth = rop_point.close / rop_start_close

        row: dict[str, object] = {
            "date": day,
            "timestamp_utc": int(brk_point.date.timestamp()),
            "brk_a_close": brk_point.close,
            "brk_a_adj_close": brk_point.adjusted_close,
            "rop_close": rop_point.close,
            "rop_adj_close": rop_point.adjusted_close,
            "brk_a_total_growth_of_1": brk_total_growth,
            "rop_total_growth_of_1": rop_total_growth,
            "brk_a_price_growth_of_1": brk_price_growth,
            "rop_price_growth_of_1": rop_price_growth,
            "brk_a_total_return_pct": (brk_total_growth - 1.0) * 100.0,
            "rop_total_return_pct": (rop_total_growth - 1.0) * 100.0,
            "brk_a_price_return_pct": (brk_price_growth - 1.0) * 100.0,
            "rop_price_return_pct": (rop_price_growth - 1.0) * 100.0,
        }

        for key, meta in benchmark_meta.items():
            point = meta["by_day"].get(day)  # type: ignore[index]
            if point is None:
                row[f"{key}_close"] = None
                row[f"{key}_adj_close"] = None
                row[f"{key}_total_growth_of_1"] = None
                row[f"{key}_price_growth_of_1"] = None
                row[f"{key}_total_return_pct"] = None
                row[f"{key}_price_return_pct"] = None
                continue

            benchmark_point = point
            total_growth = benchmark_point.adjusted_close / float(meta["start_adj"])
            price_growth = benchmark_point.close / float(meta["start_close"])
            row[f"{key}_close"] = benchmark_point.close
            row[f"{key}_adj_close"] = benchmark_point.adjusted_close
            row[f"{key}_total_growth_of_1"] = total_growth
            row[f"{key}_price_growth_of_1"] = price_growth
            row[f"{key}_total_return_pct"] = (total_growth - 1.0) * 100.0
            row[f"{key}_price_return_pct"] = (price_growth - 1.0) * 100.0

        rows.append(row)

    benchmark_info = {
        key: {
            "label": BENCHMARK_DEFS[key]["label"],
            "shortLabel": BENCHMARK_DEFS[key]["shortLabel"],
            "detail": BENCHMARK_DEFS[key]["detail"],
            "color": BENCHMARK_DEFS[key]["color"],
            "dash": BENCHMARK_DEFS[key]["dash"],
            "startDate": meta["start_date"],
        }
        for key, meta in benchmark_meta.items()
    }

    return rows, benchmark_info


def write_csv(rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "date",
        "timestamp_utc",
        "brk_a_close",
        "brk_a_adj_close",
        "rop_close",
        "rop_adj_close",
        "brk_a_total_growth_of_1",
        "rop_total_growth_of_1",
        "brk_a_price_growth_of_1",
        "rop_price_growth_of_1",
        "brk_a_total_return_pct",
        "rop_total_return_pct",
        "brk_a_price_return_pct",
        "rop_price_return_pct",
        "spy_close",
        "spy_adj_close",
        "spy_total_growth_of_1",
        "spy_price_growth_of_1",
        "spy_total_return_pct",
        "spy_price_return_pct",
        "acwi_close",
        "acwi_adj_close",
        "acwi_total_growth_of_1",
        "acwi_price_growth_of_1",
        "acwi_total_return_pct",
        "acwi_price_return_pct",
    ]

    with CSV_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_roper_events(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    row_dates = [str(row["date"]) for row in rows]
    resolved: list[dict[str, object]] = []

    for event in ROPER_EVENT_DEFS:
        row_index = len(row_dates) - 1
        for index, row_date in enumerate(row_dates):
            if row_date >= event["date"]:
                row_index = index
                break

        resolved.append(
            {
                "id": event["id"],
                "date": event["date"],
                "plotDate": row_dates[row_index],
                "rowIndex": row_index,
                "label": event["label"],
                "title": event["title"],
                "detail": event["detail"],
            }
        )

    return resolved


def fmt_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def fmt_multiple(value: float) -> str:
    return f"{value:.1f}x"


def build_mode_summary(
    rows: list[dict[str, object]],
    *,
    mode_key: str,
    label: str,
    detail: str,
    value_label: str,
    brk_value_key: str,
    rop_value_key: str,
    brk_growth_key: str,
    rop_growth_key: str,
) -> dict[str, object]:
    start = datetime.fromtimestamp(int(rows[0]["timestamp_utc"]), tz=timezone.utc)
    end = datetime.fromtimestamp(int(rows[-1]["timestamp_utc"]), tz=timezone.utc)
    duration_years = (end - start).days / 365.2425

    brk_multiple = float(rows[-1][brk_growth_key])
    rop_multiple = float(rows[-1][rop_growth_key])
    brk_cagr = brk_multiple ** (1 / duration_years) - 1
    rop_cagr = rop_multiple ** (1 / duration_years) - 1

    brk_peak_row = max(rows, key=lambda row: float(row[brk_value_key]))
    rop_peak_row = max(rows, key=lambda row: float(row[rop_value_key]))

    brk_peak = float(brk_peak_row[brk_value_key])
    rop_peak = float(rop_peak_row[rop_value_key])
    brk_latest = float(rows[-1][brk_value_key])
    rop_latest = float(rows[-1][rop_value_key])
    brk_drawdown = brk_latest / brk_peak - 1.0
    rop_drawdown = rop_latest / rop_peak - 1.0

    return {
        "key": mode_key,
        "label": label,
        "detail": detail,
        "valueLabel": value_label,
        "latestDate": rows[-1]["date"],
        "brkMultiple": brk_multiple,
        "ropMultiple": rop_multiple,
        "brkCagr": brk_cagr,
        "ropCagr": rop_cagr,
        "brkPeak": brk_peak,
        "ropPeak": rop_peak,
        "brkPeakDate": brk_peak_row["date"],
        "ropPeakDate": rop_peak_row["date"],
        "brkLatest": brk_latest,
        "ropLatest": rop_latest,
        "brkDrawdown": brk_drawdown,
        "ropDrawdown": rop_drawdown,
    }


def build_html(
    rows: list[dict[str, object]],
    benchmark_info: dict[str, dict[str, object]],
) -> str:
    start = datetime.fromtimestamp(int(rows[0]["timestamp_utc"]), tz=timezone.utc)
    end = datetime.fromtimestamp(int(rows[-1]["timestamp_utc"]), tz=timezone.utc)
    roper_events = build_roper_events(rows)

    mode_summaries = {
        "total": build_mode_summary(
            rows,
            mode_key="total",
            label="With dividends",
            detail="Uses adjusted close, which captures dividend reinvestment and Yahoo's standard price adjustments.",
            value_label="Adjusted close",
            brk_value_key="brk_a_adj_close",
            rop_value_key="rop_adj_close",
            brk_growth_key="brk_a_total_growth_of_1",
            rop_growth_key="rop_total_growth_of_1",
        ),
        "price": build_mode_summary(
            rows,
            mode_key="price",
            label="Without dividends",
            detail="Uses Yahoo's daily close series, so the chart reflects price-only performance without dividend reinvestment.",
            value_label="Close",
            brk_value_key="brk_a_close",
            rop_value_key="rop_close",
            brk_growth_key="brk_a_price_growth_of_1",
            rop_growth_key="rop_price_growth_of_1",
        ),
    }

    chart_rows = [
        {
            "date": str(row["date"]),
            "timestamp": int(row["timestamp_utc"]) * 1000,
            "brkAdj": round(float(row["brk_a_adj_close"]), 6),
            "ropAdj": round(float(row["rop_adj_close"]), 6),
            "brkClose": round(float(row["brk_a_close"]), 6),
            "ropClose": round(float(row["rop_close"]), 6),
            "brkTotalGrowth": round(float(row["brk_a_total_growth_of_1"]), 10),
            "ropTotalGrowth": round(float(row["rop_total_growth_of_1"]), 10),
            "brkPriceGrowth": round(float(row["brk_a_price_growth_of_1"]), 10),
            "ropPriceGrowth": round(float(row["rop_price_growth_of_1"]), 10),
            "brkTotalReturnPct": round(float(row["brk_a_total_return_pct"]), 6),
            "ropTotalReturnPct": round(float(row["rop_total_return_pct"]), 6),
            "brkPriceReturnPct": round(float(row["brk_a_price_return_pct"]), 6),
            "ropPriceReturnPct": round(float(row["rop_price_return_pct"]), 6),
            "spyAdj": None if row["spy_adj_close"] is None else round(float(row["spy_adj_close"]), 6),
            "spyClose": None if row["spy_close"] is None else round(float(row["spy_close"]), 6),
            "spyTotalGrowth": None
            if row["spy_total_growth_of_1"] is None
            else round(float(row["spy_total_growth_of_1"]), 10),
            "spyPriceGrowth": None
            if row["spy_price_growth_of_1"] is None
            else round(float(row["spy_price_growth_of_1"]), 10),
            "spyTotalReturnPct": None
            if row["spy_total_return_pct"] is None
            else round(float(row["spy_total_return_pct"]), 6),
            "spyPriceReturnPct": None
            if row["spy_price_return_pct"] is None
            else round(float(row["spy_price_return_pct"]), 6),
            "acwiAdj": None if row["acwi_adj_close"] is None else round(float(row["acwi_adj_close"]), 6),
            "acwiClose": None if row["acwi_close"] is None else round(float(row["acwi_close"]), 6),
            "acwiTotalGrowth": None
            if row["acwi_total_growth_of_1"] is None
            else round(float(row["acwi_total_growth_of_1"]), 10),
            "acwiPriceGrowth": None
            if row["acwi_price_growth_of_1"] is None
            else round(float(row["acwi_price_growth_of_1"]), 10),
            "acwiTotalReturnPct": None
            if row["acwi_total_return_pct"] is None
            else round(float(row["acwi_total_return_pct"]), 6),
            "acwiPriceReturnPct": None
            if row["acwi_price_return_pct"] is None
            else round(float(row["acwi_price_return_pct"]), 6),
        }
        for row in rows
    ]

    data_json = json.dumps(chart_rows, separators=(",", ":"))
    summary_json = json.dumps(mode_summaries, separators=(",", ":"))
    benchmark_json = json.dumps(benchmark_info, separators=(",", ":"))
    event_json = json.dumps(roper_events, separators=(",", ":"))
    source_note = (
        "Source: Yahoo Finance chart API daily close and adjusted close. "
        "Roper event markers use short synthetic summaries and approximate dates, not the full case text. "
        "Benchmark rebasing depends on the selected mode. "
        f"Latest common Berkshire/Roper trading date in the saved data is {fmt_date(end)}."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Berkshire Hathaway vs Roper Technologies Return Comparison</title>
  <style>
    :root {{
      --bg: #eef4f7;
      --text: #13222d;
      --muted: #4d6475;
      --grid: #d8e3eb;
      --border: #a8bcc9;
      --blue: #0d6b9f;
      --orange: #ca5a1b;
      --event: #a323ad;
      --spy: #d6b98d;
      --acwi: #a8c1d6;
      --shadow: 0 16px 34px rgba(19, 34, 45, 0.08);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.72) 30%, transparent 60%),
        linear-gradient(135deg, #edf4f7, #e5eef3 48%, #dde8ee);
      color: var(--text);
      font-family: "Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif;
    }}

    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 28px 28px;
    }}

    .header {{
      margin-bottom: 12px;
    }}

    .title-wrap {{
      max-width: 900px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2rem, 3vw, 3.3rem);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }}

    .subtitle {{
      margin: 12px 0 0;
      font-size: 1.02rem;
      line-height: 1.45;
      color: var(--muted);
      max-width: 920px;
    }}

    .controls {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-start;
      align-items: flex-start;
      margin-top: 14px;
    }}

    .control-group {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      padding: 8px 10px;
      border: 1px solid rgba(168, 188, 201, 0.65);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.76);
      box-shadow: var(--shadow);
    }}

    .control-label {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      padding: 0 4px;
    }}

    .toggle-button {{
      border: 1px solid #c8d7e0;
      background: rgba(255, 255, 255, 0.92);
      color: var(--text);
      border-radius: 999px;
      padding: 9px 14px;
      font-size: 0.95rem;
      cursor: pointer;
      transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
    }}

    .toggle-button.active {{
      background: var(--text);
      border-color: var(--text);
      color: #ffffff;
    }}

    .legend {{
      display: flex;
      gap: 18px;
      align-items: center;
      flex-wrap: wrap;
      margin: 14px 0 0;
      padding: 0 4px;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    #legend-detail {{
      flex: 1 1 100%;
      max-width: 100%;
    }}

    .legend-item {{
      display: inline-flex;
      gap: 10px;
      align-items: center;
    }}

    .legend-line {{
      width: 34px;
      height: 0;
      border-top: 3px solid;
      border-radius: 999px;
    }}

    .legend-line.blue {{
      border-color: var(--blue);
    }}

    .legend-line.orange {{
      border-color: var(--orange);
    }}

    .legend-line.spy {{
      border-color: var(--spy);
      border-top-style: dashed;
      border-top-width: 2px;
    }}

    .legend-line.acwi {{
      border-color: var(--acwi);
      border-top-style: dashed;
      border-top-width: 2px;
    }}

    .chart-viewport {{
      width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 4px;
    }}

    .chart-shell {{
      position: relative;
      width: 100%;
      min-width: 940px;
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid rgba(168, 188, 201, 0.7);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 14px;
      overflow: hidden;
    }}

    svg {{
      display: block;
      width: 100%;
      height: auto;
    }}

    .tooltip {{
      position: absolute;
      min-width: 220px;
      max-width: 290px;
      pointer-events: none;
      background: rgba(19, 34, 45, 0.82);
      color: #ffffff;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
      padding: 10px 12px;
      box-shadow: 0 10px 22px rgba(0, 0, 0, 0.14);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      opacity: 0;
      transition: opacity 80ms ease;
    }}

    .tooltip.visible {{
      opacity: 1;
    }}

    .tooltip-date {{
      font-size: 0.84rem;
      font-weight: 700;
      margin-bottom: 6px;
    }}

    .tooltip-mode {{
      font-size: 0.7rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.76);
      margin-bottom: 6px;
    }}

    .tooltip-row {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 6px 8px;
      margin-top: 4px;
      align-items: baseline;
      font-size: 0.82rem;
      line-height: 1.25;
    }}

    .tooltip-swatch {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-top: 2px;
    }}

    .tooltip-swatch.blue {{
      background: var(--blue);
    }}

    .tooltip-swatch.orange {{
      background: var(--orange);
    }}

    .tooltip-swatch.spy {{
      background: var(--spy);
    }}

    .tooltip-swatch.acwi {{
      background: var(--acwi);
    }}

    .event-popover {{
      position: absolute;
      min-width: 280px;
      max-width: 360px;
      padding: 12px 14px 13px;
      border-radius: 16px;
      border: 1px solid rgba(163, 35, 173, 0.24);
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 18px 34px rgba(19, 34, 45, 0.12);
      opacity: 0;
      transform: translateY(6px);
      transition: opacity 100ms ease, transform 100ms ease;
      pointer-events: none;
    }}

    .event-popover.visible {{
      opacity: 1;
      transform: translateY(0);
    }}

    .event-popover-date {{
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--event);
    }}

    .event-popover-title {{
      margin-top: 6px;
      font-size: 0.98rem;
      font-weight: 700;
      line-height: 1.35;
      color: var(--text);
    }}

    .event-popover-body {{
      margin: 8px 0 0;
      font-size: 0.88rem;
      line-height: 1.5;
      color: var(--muted);
    }}

    .footnote {{
      margin: 14px 2px 0;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}

    @media (max-width: 1120px) {{
      .controls {{
        justify-content: flex-start;
      }}
    }}

    @media (max-width: 960px) {{
      .controls {{
        flex-direction: column;
        align-items: stretch;
        gap: 12px;
      }}

      .control-group {{
        width: 100%;
        justify-content: flex-start;
        border-radius: 18px;
        padding: 10px 12px;
      }}

      .control-label {{
        flex: 0 0 100%;
        padding: 0 0 2px;
      }}

      .toggle-button {{
        flex: 1 1 auto;
        min-height: 42px;
        padding: 10px 12px;
      }}

      .legend {{
        gap: 10px 14px;
        font-size: 0.88rem;
      }}
    }}

    @media (max-width: 720px) {{
      .page {{
        padding: 14px 10px 20px;
      }}

      h1 {{
        font-size: clamp(1.55rem, 8vw, 2.2rem);
      }}

      .subtitle {{
        margin-top: 8px;
        font-size: 0.92rem;
        line-height: 1.4;
      }}

      .chart-viewport {{
        margin: 0 -2px;
        padding-bottom: 8px;
      }}

      .chart-shell {{
        min-width: 900px;
        padding: 10px;
        border-radius: 18px;
      }}

      .legend {{
        margin-top: 10px;
        padding: 0 2px;
        font-size: 0.84rem;
      }}

      .legend-line {{
        width: 24px;
      }}

      .tooltip {{
        min-width: 170px;
        max-width: 220px;
        padding: 8px 10px;
      }}

      .event-popover {{
        min-width: 220px;
        max-width: min(300px, calc(100vw - 28px));
      }}

      .event-popover-title {{
        font-size: 0.9rem;
      }}

      .event-popover-body {{
        font-size: 0.82rem;
        line-height: 1.4;
      }}

      .footnote {{
        font-size: 0.82rem;
        line-height: 1.4;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="header">
      <div class="title-wrap">
        <h1>Berkshire Hathaway vs Roper Technologies</h1>
        <p class="subtitle">
          Daily return comparison, normalized to $1 using the longest common Berkshire and Roper history
          available. The return-basis toggle switches between adjusted close and plain close, and the
          rebasing toggle lets you choose exact like-for-like (`Common Start`), longest-history
          (`Own Start`), or benchmark-only reset (`Benchmark Sync`). The purple event labels on the
          Roper line can be clicked to toggle concise milestone notes on the chart.
        </p>
      </div>
    </div>

    <div class="chart-viewport">
      <div class="chart-shell" id="chart-shell">
        <svg id="chart" viewBox="0 0 1260 720" role="img" aria-label="Interactive Berkshire Hathaway versus Roper Technologies return comparison">
          <defs>
            <clipPath id="plot-clip">
              <rect x="96" y="56" width="1088" height="566" rx="18"></rect>
            </clipPath>
          </defs>
          <rect x="0" y="0" width="1260" height="720" rx="24" fill="#ffffff"></rect>
          <g id="grid-layer"></g>
          <g id="axis-layer"></g>
          <g clip-path="url(#plot-clip)">
            <path id="acwi-line" fill="none" stroke="#a8c1d6" stroke-width="2" stroke-dasharray="6 6" stroke-linejoin="round" stroke-linecap="round"></path>
            <path id="spy-line" fill="none" stroke="#d6b98d" stroke-width="2" stroke-dasharray="8 7" stroke-linejoin="round" stroke-linecap="round"></path>
            <path id="brk-line" fill="none" stroke="#0d6b9f" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"></path>
            <path id="rop-line" fill="none" stroke="#ca5a1b" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"></path>
            <line id="hover-line" x1="0" y1="56" x2="0" y2="622" stroke="#6d8393" stroke-width="1.4" stroke-dasharray="4 5" opacity="0"></line>
            <circle id="brk-marker" r="5.5" fill="#0d6b9f" stroke="#ffffff" stroke-width="2" opacity="0"></circle>
            <circle id="rop-marker" r="5.5" fill="#ca5a1b" stroke="#ffffff" stroke-width="2" opacity="0"></circle>
            <circle id="spy-marker" r="4.6" fill="#d6b98d" stroke="#ffffff" stroke-width="1.8" opacity="0"></circle>
            <circle id="acwi-marker" r="4.6" fill="#a8c1d6" stroke="#ffffff" stroke-width="1.8" opacity="0"></circle>
          </g>
          <rect id="hover-target" x="96" y="56" width="1088" height="566" fill="transparent"></rect>
          <g id="event-layer"></g>
        </svg>
        <div class="tooltip" id="tooltip" aria-hidden="true"></div>
        <div class="event-popover" id="event-popover" aria-hidden="true">
          <div class="event-popover-date" id="event-popover-date"></div>
          <div class="event-popover-title" id="event-popover-title"></div>
          <p class="event-popover-body" id="event-popover-body"></p>
        </div>
      </div>
    </div>

    <div class="legend" aria-hidden="true">
      <span class="legend-item"><span class="legend-line blue"></span> Berkshire Hathaway (Class A)</span>
      <span class="legend-item"><span class="legend-line orange"></span> Roper Technologies</span>
      <span class="legend-item"><span class="legend-line spy"></span> S&amp;P 500 (SPY)</span>
      <span class="legend-item"><span class="legend-line acwi"></span> World Equity Proxy (ACWI)</span>
      <span id="legend-detail"></span>
    </div>

    <div class="controls">
      <div class="control-group" role="group" aria-label="Return basis">
        <span class="control-label">Return basis</span>
        <button class="toggle-button mode-button" data-mode="total">With dividends</button>
        <button class="toggle-button mode-button" data-mode="price">Without dividends</button>
      </div>
      <div class="control-group" role="group" aria-label="Rebasing mode">
        <span class="control-label">Rebasing</span>
        <button class="toggle-button rebase-button" data-rebase="common">Common Start</button>
        <button class="toggle-button rebase-button" data-rebase="own">Own Start</button>
        <button class="toggle-button rebase-button" data-rebase="sync">Benchmark Sync</button>
      </div>
      <div class="control-group" role="group" aria-label="Chart scale">
        <span class="control-label">Scale</span>
        <button class="toggle-button scale-button" data-scale="linear">Linear</button>
        <button class="toggle-button scale-button" data-scale="log">Log</button>
      </div>
    </div>

    <p class="footnote">{source_note}</p>
  </div>

  <script>
    const rows = {data_json};
    const modeSummaries = {summary_json};
    const benchmarkInfo = {benchmark_json};
    const roperEvents = {event_json};

    const modeConfig = {{
      total: {{
        valueKeys: {{
          brk: "brkAdj",
          rop: "ropAdj",
          spy: "spyAdj",
          acwi: "acwiAdj"
        }}
      }},
      price: {{
        valueKeys: {{
          brk: "brkClose",
          rop: "ropClose",
          spy: "spyClose",
          acwi: "acwiClose"
        }}
      }}
    }};

    const seriesOrder = ["acwi", "spy", "brk", "rop"];
    const benchmarkSet = new Set(["spy", "acwi"]);
    const seriesMeta = {{
      brk: {{ shortLabel: "BRK.A" }},
      rop: {{ shortLabel: "ROP" }},
      spy: {{ shortLabel: benchmarkInfo.spy.shortLabel }},
      acwi: {{ shortLabel: benchmarkInfo.acwi.shortLabel }}
    }};

    const dims = {{
      width: 1260,
      height: 720,
      left: 96,
      top: 56,
      plotWidth: 1088,
      plotHeight: 566
    }};
    dims.right = dims.left + dims.plotWidth;
    dims.bottom = dims.top + dims.plotHeight;

    const colors = {{
      brk: "#0d6b9f",
      rop: "#ca5a1b",
      event: "#a323ad",
      eventLight: "#dca2e3",
      eventFill: "rgba(163, 35, 173, 0.12)",
      spy: "#d6b98d",
      acwi: "#a8c1d6",
      grid: "#d8e3eb",
      axis: "#4d6475",
      border: "#a8bcc9",
      plot: "#eef4f7"
    }};

    const MS_PER_YEAR = 365.2425 * 24 * 60 * 60 * 1000;

    const svg = document.getElementById("chart");
    const gridLayer = document.getElementById("grid-layer");
    const axisLayer = document.getElementById("axis-layer");
    const eventLayer = document.getElementById("event-layer");
    const brkLine = document.getElementById("brk-line");
    const ropLine = document.getElementById("rop-line");
    const spyLine = document.getElementById("spy-line");
    const acwiLine = document.getElementById("acwi-line");
    const hoverLine = document.getElementById("hover-line");
    const brkMarker = document.getElementById("brk-marker");
    const ropMarker = document.getElementById("rop-marker");
    const spyMarker = document.getElementById("spy-marker");
    const acwiMarker = document.getElementById("acwi-marker");
    const hoverTarget = document.getElementById("hover-target");
    const tooltip = document.getElementById("tooltip");
    const chartShell = document.getElementById("chart-shell");
    const eventPopover = document.getElementById("event-popover");
    const eventPopoverDate = document.getElementById("event-popover-date");
    const eventPopoverTitle = document.getElementById("event-popover-title");
    const eventPopoverBody = document.getElementById("event-popover-body");
    const modeButtons = [...document.querySelectorAll(".mode-button")];
    const rebaseButtons = [...document.querySelectorAll(".rebase-button")];
    const scaleButtons = [...document.querySelectorAll(".scale-button")];

    const legendDetail = document.getElementById("legend-detail");
    const maxTimestamp = rows[rows.length - 1].timestamp;

    function firstIndexFor(key) {{
      return rows.findIndex((row) => row[key] != null);
    }}

    const firstAvailableIndex = {{
      brk: 0,
      rop: 0,
      spy: firstIndexFor("spyAdj"),
      acwi: firstIndexFor("acwiAdj")
    }};

    const commonStartIndex = Math.max(
      firstAvailableIndex.brk,
      firstAvailableIndex.rop,
      firstAvailableIndex.spy,
      firstAvailableIndex.acwi
    );
    const benchmarkSyncIndex = Math.max(firstAvailableIndex.spy, firstAvailableIndex.acwi);

    const rebaseConfig = {{
      common: {{
        label: "Common Start",
        detail: `All four lines rebased together at ${{rows[commonStartIndex].date}} for an exact like-for-like window.`,
        domainStartIndex: commonStartIndex,
        baselineIndex(series) {{
          return commonStartIndex;
        }},
        visibleFrom(series) {{
          return commonStartIndex;
        }}
      }},
      own: {{
        label: "Own Start",
        detail: "Each line starts at its own first available date, which keeps the longest available history.",
        domainStartIndex: 0,
        baselineIndex(series) {{
          return firstAvailableIndex[series];
        }},
        visibleFrom(series) {{
          return firstAvailableIndex[series];
        }}
      }},
      sync: {{
        label: "Benchmark Sync",
        detail: `BRK.A and ROP keep their original base, while SPY and ACWI both reset together at ${{rows[benchmarkSyncIndex].date}}.`,
        domainStartIndex: 0,
        baselineIndex(series) {{
          return benchmarkSet.has(series) ? benchmarkSyncIndex : firstAvailableIndex[series];
        }},
        visibleFrom(series) {{
          return benchmarkSet.has(series) ? benchmarkSyncIndex : firstAvailableIndex[series];
        }}
      }}
    }};

    let currentMode = "total";
    let currentRebase = "own";
    let currentScale = "log";
    let currentState = null;
    let activeEventId = null;

    function svgText(x, y, text, options = {{}}) {{
      const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
      node.setAttribute("x", x);
      node.setAttribute("y", y);
      node.setAttribute("fill", options.fill || colors.axis);
      node.setAttribute("font-size", options.fontSize || 13);
      node.setAttribute("font-family", '"Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif');
      if (options.anchor) {{
        node.setAttribute("text-anchor", options.anchor);
      }}
      if (options.weight) {{
        node.setAttribute("font-weight", options.weight);
      }}
      node.textContent = text;
      return node;
    }}

    function svgLine(x1, y1, x2, y2, options = {{}}) {{
      const node = document.createElementNS("http://www.w3.org/2000/svg", "line");
      node.setAttribute("x1", x1);
      node.setAttribute("y1", y1);
      node.setAttribute("x2", x2);
      node.setAttribute("y2", y2);
      node.setAttribute("stroke", options.stroke || colors.grid);
      node.setAttribute("stroke-width", options.width || 1);
      if (options.dash) {{
        node.setAttribute("stroke-dasharray", options.dash);
      }}
      return node;
    }}

    function svgRect(x, y, width, height, options = {{}}) {{
      const node = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      node.setAttribute("x", x);
      node.setAttribute("y", y);
      node.setAttribute("width", width);
      node.setAttribute("height", height);
      if (options.rx) {{
        node.setAttribute("rx", options.rx);
      }}
      node.setAttribute("fill", options.fill || "none");
      if (options.stroke) {{
        node.setAttribute("stroke", options.stroke);
      }}
      if (options.strokeWidth) {{
        node.setAttribute("stroke-width", options.strokeWidth);
      }}
      return node;
    }}

    function svgCircle(cx, cy, r, options = {{}}) {{
      const node = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      node.setAttribute("cx", cx);
      node.setAttribute("cy", cy);
      node.setAttribute("r", r);
      node.setAttribute("fill", options.fill || "none");
      if (options.stroke) {{
        node.setAttribute("stroke", options.stroke);
      }}
      if (options.strokeWidth) {{
        node.setAttribute("stroke-width", options.strokeWidth);
      }}
      if (options.opacity != null) {{
        node.setAttribute("opacity", options.opacity);
      }}
      return node;
    }}

    function svgPolygon(points, options = {{}}) {{
      const node = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      node.setAttribute(
        "points",
        points.map((point) => `${{point[0]}},${{point[1]}}`).join(" ")
      );
      node.setAttribute("fill", options.fill || "none");
      if (options.stroke) {{
        node.setAttribute("stroke", options.stroke);
      }}
      if (options.strokeWidth) {{
        node.setAttribute("stroke-width", options.strokeWidth);
      }}
      if (options.opacity != null) {{
        node.setAttribute("opacity", options.opacity);
      }}
      return node;
    }}

    function clearNode(node) {{
      while (node.firstChild) {{
        node.removeChild(node.firstChild);
      }}
    }}

    function formatNumber(value, digits = 2) {{
      return new Intl.NumberFormat("en-US", {{
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      }}).format(value);
    }}

    function formatUsd(value) {{
      return "$" + formatNumber(value, 2);
    }}

    function formatMultiple(value) {{
      return formatNumber(value, 1) + "x";
    }}

    function formatPercentDecimal(value, signed = false) {{
      const percent = value * 100;
      const prefix = signed && percent >= 0 ? "+" : "";
      return prefix + formatNumber(percent, 1) + "%";
    }}

    function formatPercentPoints(value, signed = true) {{
      const prefix = signed && value >= 0 ? "+" : "";
      return prefix + formatNumber(value, 1) + "%";
    }}

    function niceStep(rawStep) {{
      const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
      const scaled = rawStep / magnitude;
      const options = [1, 2, 2.5, 5, 10];
      for (const option of options) {{
        if (scaled <= option) {{
          return option * magnitude;
        }}
      }}
      return 10 * magnitude;
    }}

    function linearTicks(maxValue) {{
      const targetSegments = 6;
      const step = niceStep(maxValue / targetSegments);
      const top = step * Math.ceil(maxValue / step);
      const ticks = [];
      for (let value = 0; value <= top + step * 0.25; value += step) {{
        ticks.push(Number(value.toFixed(10)));
      }}
      return {{ top, ticks }};
    }}

    function logTicks(minValue, maxValue) {{
      const candidates = [];
      for (let exponent = -6; exponent < 8; exponent += 1) {{
        for (const base of [1, 2, 5]) {{
          candidates.push(base * Math.pow(10, exponent));
        }}
      }}

      const floorTarget = Math.max(minValue * 0.95, candidates[0]);
      const ceilingTarget = maxValue * 1.02;

      let bottom = candidates[0];
      let top = candidates[candidates.length - 1];

      for (const tick of candidates) {{
        if (tick <= floorTarget) {{
          bottom = tick;
        }}
        if (tick >= ceilingTarget) {{
          top = tick;
          break;
        }}
      }}

      const ticks = candidates.filter((tick) => tick >= bottom && tick <= top);
      return {{ bottom, top, ticks }};
    }}

    function buildState() {{
      const valueKeys = modeConfig[currentMode].valueKeys;
      const rebase = rebaseConfig[currentRebase];
      const domainStartIndex = rebase.domainStartIndex;
      const domainStartTimestamp = rows[domainStartIndex].timestamp;
      const domainSpan = Math.max(1, maxTimestamp - domainStartTimestamp);
      const xPositions = rows.map(
        (row) => dims.left + ((row.timestamp - domainStartTimestamp) / domainSpan) * dims.plotWidth
      );
      const normalized = {{
        brk: new Array(rows.length).fill(null),
        rop: new Array(rows.length).fill(null),
        spy: new Array(rows.length).fill(null),
        acwi: new Array(rows.length).fill(null)
      }};

      let minValue = Number.POSITIVE_INFINITY;
      let maxValue = 1;
      for (let index = domainStartIndex; index < rows.length; index += 1) {{
        for (const series of seriesOrder) {{
          if (index < rebase.visibleFrom(series)) {{
            continue;
          }}
          const valueKey = valueKeys[series];
          const value = rows[index][valueKey];
          if (value == null) {{
            continue;
          }}
          const baseIndex = rebase.baselineIndex(series);
          const baseValue = rows[baseIndex][valueKey];
          if (baseValue == null) {{
            continue;
          }}
          const normalizedValue = value / baseValue;
          normalized[series][index] = normalizedValue;
          if (normalizedValue < minValue) {{
            minValue = normalizedValue;
          }}
          if (normalizedValue > maxValue) {{
            maxValue = normalizedValue;
          }}
        }}
      }}

      if (!Number.isFinite(minValue)) {{
        minValue = 1;
      }}

      return {{
        valueKeys,
        rebase,
        domainStartIndex,
        domainStartTimestamp,
        xPositions,
        normalized,
        minValue,
        maxValue
      }};
    }}

    function makeScale(minValue, maxValue) {{
      if (currentScale === "log") {{
        const {{ bottom, top, ticks }} = logTicks(minValue, maxValue);
        return {{
          bottom,
          top,
          ticks,
          label: "Growth of $1",
          yFor(value) {{
            const safe = Math.max(value, bottom);
            const ratio =
              (Math.log10(safe) - Math.log10(bottom)) /
              (Math.log10(top) - Math.log10(bottom));
            return dims.bottom - ratio * dims.plotHeight;
          }},
          tickLabel(value) {{
            if (value >= 1) {{
              return value + "x";
            }}
            if (value >= 0.1) {{
              return formatNumber(value, 1) + "x";
            }}
            return formatNumber(value, 2) + "x";
          }}
        }};
      }}

      const {{ top, ticks }} = linearTicks(maxValue * 1.02);
      return {{
        top,
        ticks,
        label: "Growth of $1",
        yFor(value) {{
          return dims.bottom - (value / top) * dims.plotHeight;
        }},
        tickLabel(value) {{
          return value === 0 ? "0x" : formatNumber(value, value < 10 ? 1 : 0) + "x";
        }}
      }};
    }}

    function xTickDates(domainStartTimestamp) {{
      const start = new Date(domainStartTimestamp);
      const end = new Date(maxTimestamp);
      const ticks = [new Date(start.getTime())];

      for (let year = start.getUTCFullYear() + 1; year <= end.getUTCFullYear(); year += 1) {{
        if (year % 5 === 0) {{
          const tick = new Date(Date.UTC(year, 0, 1));
          if (tick.getTime() < end.getTime()) {{
            ticks.push(tick);
          }}
        }}
      }}

      ticks.push(new Date(end.getTime()));

      const deduped = [];
      const minGapMs = 365 * 24 * 60 * 60 * 1000 * 3;
      for (const tick of ticks) {{
        if (deduped.length && tick.getTime() - deduped[deduped.length - 1].getTime() < minGapMs) {{
          deduped[deduped.length - 1] = tick;
        }} else {{
          deduped.push(tick);
        }}
      }}
      return deduped;
    }}

    function xTickLabel(date, domainStartTimestamp) {{
      const isBoundary = date.getTime() === domainStartTimestamp || date.getTime() === maxTimestamp;
      if (isBoundary) {{
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, "0");
        const day = String(date.getUTCDate()).padStart(2, "0");
        return `${{year}}-${{month}}-${{day}}`;
      }}
      return String(date.getUTCFullYear());
    }}

    function pathForSeries(series, state, yFor) {{
      let path = "";
      let drawing = false;
      for (let index = state.domainStartIndex; index < rows.length; index += 1) {{
        const value = state.normalized[series][index];
        if (value == null) {{
          drawing = false;
          continue;
        }}
        const x = state.xPositions[index];
        const y = yFor(value);
        path += `${{drawing ? "L" : "M"}}${{x.toFixed(2)}} ${{y.toFixed(2)}}`;
        drawing = true;
      }}
      return path;
    }}

    function visibleEvents(state) {{
      return roperEvents.filter(
        (event) =>
          event.rowIndex >= state.domainStartIndex && state.normalized.rop[event.rowIndex] != null
      );
    }}

    function selectedEvent(state) {{
      const visible = visibleEvents(state);
      if (!visible.length) {{
        return null;
      }}
      if (activeEventId == null) {{
        return null;
      }}
      const active = visible.find((event) => event.id === activeEventId) || null;
      if (!active) {{
        activeEventId = null;
      }}
      return active;
    }}

    function pinEvent(eventId) {{
      activeEventId = activeEventId === eventId ? null : eventId;
      if (!currentState) {{
        return;
      }}
      const scale = makeScale(currentState.minValue, currentState.maxValue);
      renderEventLayer(currentState, scale);
      const event = selectedEvent(currentState);
      if (event) {{
        updateHover(event.rowIndex);
      }} else {{
        hideEventPopover();
      }}
    }}

    function eventLayouts(visible, state, scale) {{
      const laneCount = 4;
      const laneRows = Array.from({{ length: laneCount }}, (_, lane) => dims.top + 18 + lane * 28);
      const laneRightEdge = new Array(laneCount).fill(dims.left - 12);
      const margin = 12;
      const layouts = new Map();

      visible.forEach((event, index) => {{
        const x = state.xPositions[event.rowIndex];
        const y = scale.yFor(state.normalized.rop[event.rowIndex]);
        const calloutText = `${{event.date.slice(0, 4)}} · ${{event.label}}`;
        const pillHeight = 26;
        const pillWidth = Math.max(110, Math.min(214, calloutText.length * 7 + 24));
        const minX = dims.left + 8;
        const maxX = dims.right - pillWidth - 8;
        const idealLeft = Math.max(minX, Math.min(maxX, x - pillWidth / 2));

        let chosenLane = -1;
        let pillX = idealLeft;
        const preferredLane = index % laneCount;

        for (let offset = 0; offset < laneCount; offset += 1) {{
          const lane = (preferredLane + offset) % laneCount;
          const shiftedLeft = Math.max(idealLeft, laneRightEdge[lane] + margin);
          if (shiftedLeft <= maxX) {{
            chosenLane = lane;
            pillX = shiftedLeft;
            break;
          }}
        }}

        if (chosenLane === -1) {{
          let bestLane = 0;
          for (let lane = 1; lane < laneCount; lane += 1) {{
            if (laneRightEdge[lane] < laneRightEdge[bestLane]) {{
              bestLane = lane;
            }}
          }}
          chosenLane = bestLane;
          pillX = Math.max(minX, Math.min(maxX, Math.max(idealLeft, laneRightEdge[chosenLane] + margin)));
        }}

        laneRightEdge[chosenLane] = pillX + pillWidth;
        const pillY = laneRows[chosenLane];
        const shaftTop = Math.min(
          Math.max(pillY + pillHeight + 8, dims.top + 8),
          y - 12
        );

        layouts.set(event.id, {{
          x,
          y,
          calloutText,
          pillX,
          pillY,
          pillWidth,
          pillHeight,
          labelCenterX: pillX + pillWidth / 2,
          labelCenterY: pillY + pillHeight / 2,
          connectorStartY: pillY + pillHeight,
          connectorEndY: shaftTop - 4,
          shaftTop,
          arrowBaseY: y - 9,
          arrowTipY: y
        }});
      }});

      return layouts;
    }}

    function renderEventLayer(state, scale) {{
      clearNode(eventLayer);
      const visible = visibleEvents(state);
      const activeEvent = selectedEvent(state);

      if (!visible.length) {{
        hideEventPopover();
        return;
      }}

      const layouts = eventLayouts(visible, state, scale);

      visible.forEach((event) => {{
        const isActive = activeEvent != null && event.id === activeEvent.id;
        const layout = layouts.get(event.id);
        if (!layout) {{
          return;
        }}
        const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
        group.setAttribute("role", "button");
        group.setAttribute("tabindex", "0");
        group.setAttribute("aria-label", `${{event.plotDate}}: ${{event.title}}`);
        group.style.cursor = "pointer";

        group.appendChild(
          svgLine(layout.x, layout.connectorStartY, layout.x, layout.connectorEndY, {{
            stroke: isActive ? colors.event : colors.eventLight,
            width: isActive ? 1.7 : 1.2,
            dash: "5 5"
          }})
        );
        group.appendChild(
          svgRect(layout.pillX, layout.pillY, layout.pillWidth, layout.pillHeight, {{
            rx: 13,
            fill: "rgba(255, 255, 255, 0.97)",
            stroke: isActive ? colors.event : colors.eventLight,
            strokeWidth: isActive ? 1.6 : 1.2
          }})
        );
        group.appendChild(
          svgText(layout.labelCenterX, layout.labelCenterY + 4, layout.calloutText, {{
            anchor: "middle",
            fontSize: 12,
            fill: colors.event,
            weight: isActive ? "700" : "600"
          }})
        );

        const shaftTop = layout.shaftTop;
        const arrowBaseY = layout.arrowBaseY - (isActive ? 1 : 0);
        const arrowHalfWidth = isActive ? 6.5 : 5.5;
        group.appendChild(
          svgLine(layout.x, shaftTop, layout.x, arrowBaseY, {{
            stroke: colors.event,
            width: isActive ? 2.8 : 2.2
          }})
        );
        group.appendChild(
          svgPolygon(
            [
              [layout.x - arrowHalfWidth, arrowBaseY],
              [layout.x + arrowHalfWidth, arrowBaseY],
              [layout.x, layout.arrowTipY + (isActive ? 1.5 : 1)]
            ],
            {{
              fill: colors.event,
              stroke: colors.event,
              strokeWidth: 1
            }}
          )
        );
        if (isActive) {{
          group.appendChild(
            svgCircle(layout.x, layout.y - 4, 11, {{
              fill: colors.eventFill
            }})
          );
          group.appendChild(
            svgLine(layout.x, shaftTop - 4, layout.x, shaftTop + 2, {{
              stroke: colors.eventLight,
              width: 4.2
            }})
          );
          group.appendChild(
            svgLine(layout.x, shaftTop - 4, layout.x, shaftTop + 2, {{
              stroke: colors.event,
              width: 2.8
            }})
          );
        }} else {{
          group.appendChild(
            svgLine(layout.x, shaftTop - 3, layout.x, shaftTop + 1, {{
              stroke: colors.eventLight,
              width: 3.2
            }})
          );
        }}
        group.appendChild(
          svgCircle(layout.x, layout.y, isActive ? 2.2 : 1.8, {{
            fill: "#ffffff",
            stroke: colors.event,
            strokeWidth: 1.2
          }})
        );

        const hitArea = svgRect(
          layout.pillX - 6,
          layout.pillY - 4,
          layout.pillWidth + 12,
          Math.max(28, layout.arrowTipY - layout.pillY + 20),
          {{
            rx: 14,
            fill: "rgba(0, 0, 0, 0)"
          }}
        );
        group.appendChild(hitArea);

        if (isActive) {{
          group.appendChild(
            svgCircle(layout.x, layout.y - 4, 7.6, {{
              fill: "none",
              stroke: colors.event,
              strokeWidth: 1.4,
              opacity: 0.35
            }})
          );
        }}

        group.addEventListener("mouseenter", () => {{
          updateHover(event.rowIndex);
        }});

        group.addEventListener("mouseleave", () => {{
          hideHover();
        }});

        group.addEventListener("click", (eventObject) => {{
          eventObject.stopPropagation();
          pinEvent(event.id);
        }});

        group.addEventListener("focus", () => {{
          updateHover(event.rowIndex);
        }});

        group.addEventListener("blur", () => {{
          hideHover();
        }});

        group.addEventListener("keydown", (eventObject) => {{
          if (eventObject.key === "Enter" || eventObject.key === " ") {{
            eventObject.preventDefault();
            pinEvent(event.id);
          }}
        }});

        eventLayer.appendChild(group);
      }});

      updateEventPopover(activeEvent, activeEvent == null ? null : layouts.get(activeEvent.id));
    }}

    function setButtonState() {{
      modeButtons.forEach((button) => {{
        button.classList.toggle("active", button.dataset.mode === currentMode);
      }});
      rebaseButtons.forEach((button) => {{
        button.classList.toggle("active", button.dataset.rebase === currentRebase);
      }});
      scaleButtons.forEach((button) => {{
        button.classList.toggle("active", button.dataset.scale === currentScale);
      }});
    }}

    function seriesStats(series, state) {{
      const startIndex = Math.max(state.domainStartIndex, state.rebase.visibleFrom(series));
      const valueKey = state.valueKeys[series];

      let firstIndex = -1;
      let peakIndex = -1;
      let peakValue = -Infinity;

      for (let index = startIndex; index < rows.length; index += 1) {{
        const normalizedValue = state.normalized[series][index];
        const rawValue = rows[index][valueKey];
        if (normalizedValue == null || rawValue == null) {{
          continue;
        }}
        if (firstIndex === -1) {{
          firstIndex = index;
        }}
        if (rawValue > peakValue) {{
          peakValue = rawValue;
          peakIndex = index;
        }}
      }}

      if (firstIndex === -1) {{
        return null;
      }}

      const lastIndex = rows.length - 1;
      const multiple = state.normalized[series][lastIndex];
      const latestValue = rows[lastIndex][valueKey];
      const durationYears = Math.max(
        (rows[lastIndex].timestamp - rows[firstIndex].timestamp) / MS_PER_YEAR,
        1 / 365.2425
      );
      const cagr = Math.pow(multiple, 1 / durationYears) - 1;

      return {{
        firstDate: rows[firstIndex].date,
        multiple,
        cagr,
        latestValue,
        peakValue,
        peakDate: rows[peakIndex].date,
        drawdown: latestValue / peakValue - 1
      }};
    }}

    function updateSummaryCards(state) {{
      const rebase = rebaseConfig[currentRebase];

      legendDetail.textContent =
        `${{rebase.detail}} SPY begins ${{benchmarkInfo.spy.startDate}} and ACWI begins ${{benchmarkInfo.acwi.startDate}}. Click any purple Roper event label for timeline notes.`;
    }}

    function renderChart() {{
      currentState = buildState();
      const state = currentState;
      const scale = makeScale(state.minValue, state.maxValue);
      clearNode(gridLayer);
      clearNode(axisLayer);

      gridLayer.appendChild(
        svgRect(dims.left, dims.top, dims.plotWidth, dims.plotHeight, {{
          rx: 18,
          fill: colors.plot,
          stroke: colors.border,
          strokeWidth: 1.3
        }})
      );

      scale.ticks.forEach((tick) => {{
        const y = scale.yFor(tick);
        gridLayer.appendChild(
          svgLine(dims.left, y, dims.right, y, {{
            stroke: tick === 0 ? colors.border : colors.grid,
            width: tick === 0 ? 1.2 : 1
          }})
        );
        axisLayer.appendChild(
          svgText(dims.left - 14, y + 4, scale.tickLabel(tick), {{
            anchor: "end"
          }})
        );
      }});

      xTickDates(state.domainStartTimestamp).forEach((tickDate) => {{
        const span = Math.max(1, maxTimestamp - state.domainStartTimestamp);
        const x =
          dims.left + ((tickDate.getTime() - state.domainStartTimestamp) / span) * dims.plotWidth;
        gridLayer.appendChild(
          svgLine(x, dims.top, x, dims.bottom, {{
            stroke: colors.grid,
            width: 1
          }})
        );
        axisLayer.appendChild(
          svgText(x, dims.bottom + 30, xTickLabel(tickDate, state.domainStartTimestamp), {{
            anchor: "middle"
          }})
        );
      }});

      axisLayer.appendChild(
        svgText(dims.left - 14, dims.top - 16, scale.label, {{
          anchor: "end",
          fontSize: 12,
          fill: colors.axis,
          weight: "600"
        }})
      );

      acwiLine.setAttribute("d", pathForSeries("acwi", state, scale.yFor));
      spyLine.setAttribute("d", pathForSeries("spy", state, scale.yFor));
      brkLine.setAttribute("d", pathForSeries("brk", state, scale.yFor));
      ropLine.setAttribute("d", pathForSeries("rop", state, scale.yFor));
      renderEventLayer(state, scale);

      setButtonState();
      updateSummaryCards(state);
      hideHover();
    }}

    function nearestIndex(targetX) {{
      let low = currentState.domainStartIndex;
      let high = rows.length - 1;

      while (low < high) {{
        const mid = Math.floor((low + high) / 2);
        if (currentState.xPositions[mid] < targetX) {{
          low = mid + 1;
        }} else {{
          high = mid;
        }}
      }}

      if (low === currentState.domainStartIndex) {{
        return low;
      }}

      const prev = currentState.xPositions[low - 1];
      const curr = currentState.xPositions[low];
      return Math.abs(prev - targetX) <= Math.abs(curr - targetX) ? low - 1 : low;
    }}

    function tooltipRow(series, swatchClass, state, index) {{
      const value = rows[index][state.valueKeys[series]];
      const growth = state.normalized[series][index];
      const label = seriesMeta[series].shortLabel;

      if (value == null || growth == null) {{
        const visibleIndex = state.rebase.visibleFrom(series);
        const note =
          currentRebase === "sync" && benchmarkSet.has(series)
            ? `rebases at ${{rows[visibleIndex].date}}`
            : `starts ${{rows[visibleIndex].date}}`;
        return `
          <div class="tooltip-row">
            <span class="tooltip-swatch ${{swatchClass}}"></span>
            <span><strong>${{label}}</strong> ${{note}}</span>
          </div>
        `;
      }}

      const returnPct = (growth - 1) * 100;
      return `
        <div class="tooltip-row">
          <span class="tooltip-swatch ${{swatchClass}}"></span>
          <span><strong>${{label}}</strong> ${{formatUsd(value)}} | ${{formatMultiple(growth)}} | ${{formatPercentPoints(returnPct)}}</span>
        </div>
      `;
    }}

    function tooltipHtml(index, state) {{
      const basisLabel = currentMode === "total" ? "Total return" : "Price only";
      return `
        <div class="tooltip-date">${{rows[index].date}}</div>
        <div class="tooltip-mode">${{basisLabel}} | ${{rebaseConfig[currentRebase].label}}</div>
        ${{tooltipRow("brk", "blue", state, index)}}
        ${{tooltipRow("rop", "orange", state, index)}}
        ${{tooltipRow("spy", "spy", state, index)}}
        ${{tooltipRow("acwi", "acwi", state, index)}}
      `;
    }}

    function setMarker(marker, x, y) {{
      if (y == null) {{
        marker.setAttribute("opacity", "0");
        return;
      }}
      marker.setAttribute("cx", x);
      marker.setAttribute("cy", y);
      marker.setAttribute("opacity", "1");
    }}

    function hideHover() {{
      hoverLine.setAttribute("opacity", "0");
      brkMarker.setAttribute("opacity", "0");
      ropMarker.setAttribute("opacity", "0");
      spyMarker.setAttribute("opacity", "0");
      acwiMarker.setAttribute("opacity", "0");
      tooltip.classList.remove("visible");
    }}

    function hideEventPopover() {{
      eventPopover.classList.remove("visible");
      eventPopover.setAttribute("aria-hidden", "true");
    }}

    function updateEventPopover(event, layout) {{
      if (!event || !layout) {{
        hideEventPopover();
        return;
      }}

      eventPopoverDate.textContent = `${{event.date}} | ${{event.label}}`;
      eventPopoverTitle.textContent = event.title;
      eventPopoverBody.textContent = event.detail;

      const shellBox = chartShell.getBoundingClientRect();
      const svgBox = svg.getBoundingClientRect();
      const scaleX = svgBox.width / dims.width;
      const scaleY = svgBox.height / dims.height;
      const popoverWidth = Math.min(Math.max(svgBox.width * 0.22, 280), 360);

      eventPopover.style.width = `${{popoverWidth}}px`;

      const anchorCenterX = svgBox.left - shellBox.left + layout.labelCenterX * scaleX;
      const anchorTopY =
        svgBox.top - shellBox.top + (layout.pillY + layout.pillHeight + 10) * scaleY;
      const maxLeft = Math.max(12, shellBox.width - popoverWidth - 12);
      const left = Math.max(12, Math.min(maxLeft, anchorCenterX - popoverWidth / 2));
      const popoverHeight = eventPopover.offsetHeight;
      const top = Math.max(12, Math.min(shellBox.height - popoverHeight - 12, anchorTopY));

      eventPopover.style.left = `${{left}}px`;
      eventPopover.style.top = `${{top}}px`;
      eventPopover.classList.add("visible");
      eventPopover.setAttribute("aria-hidden", "false");
    }}

    function updateHover(index, mouseX = null, mouseY = null) {{
      const state = currentState;
      const scale = makeScale(state.minValue, state.maxValue);
      const x = state.xPositions[index];
      const brkY = scale.yFor(state.normalized.brk[index]);
      const ropY = scale.yFor(state.normalized.rop[index]);
      const spyY =
        state.normalized.spy[index] == null ? null : scale.yFor(state.normalized.spy[index]);
      const acwiY =
        state.normalized.acwi[index] == null ? null : scale.yFor(state.normalized.acwi[index]);

      hoverLine.setAttribute("x1", x);
      hoverLine.setAttribute("x2", x);
      hoverLine.setAttribute("opacity", "1");

      setMarker(brkMarker, x, brkY);
      setMarker(ropMarker, x, ropY);
      setMarker(spyMarker, x, spyY);
      setMarker(acwiMarker, x, acwiY);

      tooltip.innerHTML = tooltipHtml(index, state);
      tooltip.classList.add("visible");

      const shellBox = chartShell.getBoundingClientRect();
      const svgBox = svg.getBoundingClientRect();
      const fallbackX = svgBox.left + ((x / dims.width) * svgBox.width);
      const fallbackY = svgBox.top + ((ropY / dims.height) * svgBox.height);
      const clientX = mouseX ?? fallbackX;
      const clientY = mouseY ?? fallbackY;

      const tooltipWidth = tooltip.offsetWidth;
      const tooltipHeight = tooltip.offsetHeight;

      let left = clientX - shellBox.left + 14;
      let top = clientY - shellBox.top + 16;

      left = Math.max(10, Math.min(shellBox.width - tooltipWidth - 10, left));
      top = Math.max(10, Math.min(shellBox.height - tooltipHeight - 10, top));

      tooltip.style.left = `${{left}}px`;
      tooltip.style.top = `${{top}}px`;
    }}

    hoverTarget.addEventListener("mousemove", (event) => {{
      const svgBox = svg.getBoundingClientRect();
      const localX = ((event.clientX - svgBox.left) / svgBox.width) * dims.width;
      const clampedX = Math.max(dims.left, Math.min(dims.right, localX));
      const index = nearestIndex(clampedX);
      updateHover(index, event.clientX, event.clientY);
    }});

    hoverTarget.addEventListener("mouseleave", () => {{
      hideHover();
    }});

    svg.addEventListener("mouseleave", () => {{
      hideHover();
    }});

    modeButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        currentMode = button.dataset.mode;
        renderChart();
      }});
    }});

    rebaseButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        currentRebase = button.dataset.rebase;
        renderChart();
      }});
    }});

    scaleButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        currentScale = button.dataset.scale;
        renderChart();
      }});
    }});

    renderChart();
  </script>
</body>
</html>
"""


def main() -> None:
    brk_points = load_series(BRK_PATH)
    rop_points = load_series(ROP_PATH)
    benchmark_points = {
        key: load_series(config["path"]) for key, config in BENCHMARK_DEFS.items()
    }

    rows, benchmark_info = align_series(brk_points, rop_points, benchmark_points)
    write_csv(rows)
    html = build_html(rows, benchmark_info)
    HTML_PATH.write_text(html)
    INDEX_PATH.write_text(html)
    SITE_DIR.mkdir(exist_ok=True)
    SITE_INDEX_PATH.write_text(html)

    start = rows[0]["date"]
    end = rows[-1]["date"]
    brk_total_multiple = float(rows[-1]["brk_a_total_growth_of_1"])
    rop_total_multiple = float(rows[-1]["rop_total_growth_of_1"])
    brk_price_multiple = float(rows[-1]["brk_a_price_growth_of_1"])
    rop_price_multiple = float(rows[-1]["rop_price_growth_of_1"])

    print(
        f"Wrote {CSV_PATH.name}, {HTML_PATH.name}, {INDEX_PATH.name}, and "
        f"{SITE_INDEX_PATH.relative_to(ROOT)}"
    )
    print(
        f"Range: {start} to {end} | "
        f"with dividends BRK.A {brk_total_multiple:.2f}x / ROP {rop_total_multiple:.2f}x | "
        f"without dividends BRK.A {brk_price_multiple:.2f}x / ROP {rop_price_multiple:.2f}x | "
        f"SPY starts {benchmark_info['spy']['startDate']} | ACWI starts {benchmark_info['acwi']['startDate']}"
    )


if __name__ == "__main__":
    main()
