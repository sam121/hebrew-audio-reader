from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from common import (
    PROCESSED_DIR,
    TRANSACTION_COLUMNS,
    TRANSFER_COLUMNS,
    ensure_dirs,
    parse_date,
    parse_decimal,
    read_csv_dicts,
    stable_id,
    write_csv,
)


DATE_WINDOW_DAYS = 7
SAME_CURRENCY_TOLERANCE = Decimal("0.01")
CROSS_CURRENCY_SGD_TOLERANCE = Decimal("75")
CROSS_CURRENCY_PCT_TOLERANCE = Decimal("0.015")
PLATFORM_SAME_CURRENCY_TOLERANCE = Decimal("100")
PLATFORM_SAME_CURRENCY_PCT_TOLERANCE = Decimal("0.02")
LARGE_SGD_REVIEW_THRESHOLD = Decimal("1000")
HIGH_CONFIDENCE_MIN = Decimal("0.90")


def row_text(row: dict[str, Any]) -> str:
    return " ".join([row.get("description_clean", ""), row.get("description_raw", ""), row.get("merchant", "")]).lower()


def mentions_endowus(row: dict[str, Any]) -> bool:
    return "endowus" in row_text(row)


def mentions_ibkr(row: dict[str, Any]) -> bool:
    text = row_text(row)
    return row.get("institution") == "ibkr" or "interactive brokers" in text or "interactive br " in text


def is_ibkr_cash_flow(row: dict[str, Any]) -> bool:
    text = row_text(row)
    return row.get("institution") == "ibkr" and any(
        token in text for token in ["deposit |", "withdrawal |", "cash receipts", "electronic fund transfers", "disbursement"]
    )


def is_platform_or_investment_cash_flow(row: dict[str, Any]) -> bool:
    text = row_text(row)
    if row.get("institution") in {"ibkr", "stripe", "vanguard", "endowus", "evelyn"}:
        return True
    if row.get("category") == "investment":
        return True
    return any(token in text for token in ["uob kay hian", "buy fund mgt", "supplementary retirement scheme", "investment & securities"])


def is_candidate(row: dict[str, Any]) -> bool:
    if mentions_endowus(row):
        return False
    if row.get("institution") == "ibkr":
        return is_ibkr_cash_flow(row)
    if mentions_ibkr(row):
        return True
    if str(row.get("is_transfer_candidate", "")).lower() == "true":
        return True
    return row.get("category") in {"transfer", "investment"}


def is_assumed_one_sided_transfer(row: dict[str, Any]) -> bool:
    return mentions_endowus(row) or mentions_ibkr(row)


def decimal_field(row: dict[str, Any], field: str) -> Decimal | None:
    return parse_decimal(row.get(field))


def date_field(row: dict[str, Any]) -> date | None:
    return parse_date(row.get("date"))


def account_label(row: dict[str, Any]) -> str:
    return f"{row.get('institution', '')}:{row.get('account_id', '')}"


def is_card_payment_pair(outflow: dict[str, Any], inflow: dict[str, Any]) -> bool:
    text = " ".join([outflow.get("description_clean", ""), inflow.get("description_clean", "")]).lower()
    accounts = {outflow.get("account_type", ""), inflow.get("account_type", "")}
    return "credit_card" in accounts and any(token in text for token in ["autopay", "card centre", "dbs card", "bill payment"])


def is_same_account_card_reversal(outflow: dict[str, Any], inflow: dict[str, Any]) -> bool:
    text = " ".join([outflow.get("description_clean", ""), inflow.get("description_clean", "")]).lower()
    return (
        account_label(outflow) == account_label(inflow)
        and outflow.get("account_type") == "credit_card"
        and inflow.get("account_type") == "credit_card"
        and "giro return" in text
        and any(token in text for token in ["auto-pyt from acct", "payment - dbs internet/wireless", "bill payment"])
    )


def is_wise_conversion(row: dict[str, Any]) -> bool:
    text = row_text(row)
    return row.get("institution") == "wise" and (" debit | conversion" in text or " credit | conversion" in text or text.startswith("moved "))


def is_wise_external_send(row: dict[str, Any]) -> bool:
    text = row_text(row)
    return row.get("institution") == "wise" and "sent money to" in text


def is_bank_receipt(row: dict[str, Any]) -> bool:
    return row.get("institution") in {"dbs", "barclays", "halifax"}


def candidate_score(outflow: dict[str, Any], inflow: dict[str, Any]) -> tuple[Decimal, str] | None:
    out_date = date_field(outflow)
    in_date = date_field(inflow)
    out_amt = decimal_field(outflow, "amount")
    in_amt = decimal_field(inflow, "amount")
    out_amt_sgd = decimal_field(outflow, "amount_sgd")
    in_amt_sgd = decimal_field(inflow, "amount_sgd")
    if out_date is None or in_date is None or out_amt is None or in_amt is None:
        return None
    if out_amt >= 0 or in_amt <= 0:
        return None
    same_account_reversal = is_same_account_card_reversal(outflow, inflow)
    if account_label(outflow) == account_label(inflow) and not same_account_reversal:
        return None
    day_gap = abs((in_date - out_date).days)
    if day_gap > DATE_WINDOW_DAYS:
        return None

    score = Decimal("0.94")
    reasons: list[str] = []
    if outflow.get("currency") == inflow.get("currency"):
        amount_gap = abs(abs(out_amt) - in_amt)
        base_amount = max(abs(out_amt), in_amt)
        pct_gap = amount_gap / base_amount if base_amount else Decimal("1")
        if amount_gap <= SAME_CURRENCY_TOLERANCE:
            reasons.extend(["same currency", "equal amount"])
        elif (
            (mentions_ibkr(outflow) or mentions_ibkr(inflow) or is_platform_or_investment_cash_flow(outflow) or is_platform_or_investment_cash_flow(inflow))
            and amount_gap <= PLATFORM_SAME_CURRENCY_TOLERANCE
            and pct_gap <= PLATFORM_SAME_CURRENCY_PCT_TOLERANCE
        ):
            score -= Decimal("0.02")
            reasons.extend(["same currency", f"near platform/investment amount gap {amount_gap:.2f}", f"{pct_gap:.2%} gap"])
        else:
            return None
    elif (mentions_ibkr(outflow) or mentions_ibkr(inflow)) and abs(abs(out_amt) - in_amt) <= SAME_CURRENCY_TOLERANCE:
        score -= Decimal("0.03")
        reasons.extend(["IBKR cash flow", "equal original numeric amount"])
    else:
        if out_amt_sgd is None or in_amt_sgd is None:
            return None
        amount_gap_sgd = abs(abs(out_amt_sgd) - in_amt_sgd)
        base_sgd = max(abs(out_amt_sgd), in_amt_sgd)
        pct_gap = amount_gap_sgd / base_sgd if base_sgd else Decimal("1")
        if amount_gap_sgd > CROSS_CURRENCY_SGD_TOLERANCE and pct_gap > CROSS_CURRENCY_PCT_TOLERANCE:
            return None
        score -= Decimal("0.04")
        reasons.extend(["cross currency", f"SGD equivalent gap {amount_gap_sgd:.2f}", f"{pct_gap:.2%} gap"])
    if day_gap == 0:
        score += Decimal("0.03")
        reasons.append("same day")
    else:
        score -= Decimal(day_gap) * Decimal("0.01")
        reasons.append(f"{day_gap} day gap")
    if outflow.get("institution") == inflow.get("institution"):
        score += Decimal("0.01")
        reasons.append("same institution")
    if is_card_payment_pair(outflow, inflow):
        score += Decimal("0.03")
        reasons.append("card repayment wording")
    if same_account_reversal:
        score += Decimal("0.03")
        reasons.append("same-card GIRO return reversal")
    if outflow.get("category") == "investment" or inflow.get("category") == "investment":
        reasons.append("investment funding")
    if is_wise_external_send(outflow) and is_bank_receipt(inflow) and outflow.get("owner") == inflow.get("owner"):
        score += Decimal("0.04")
        reasons.append("Wise external send to bank")
    elif is_wise_external_send(outflow) and is_bank_receipt(inflow):
        score -= Decimal("0.02")
        reasons.append("cross-owner Wise send to bank; prefer recipient Wise receipt if present")
    if is_wise_conversion(outflow) and is_bank_receipt(inflow):
        score -= Decimal("0.05")
        reasons.append("prefer explicit Wise send over conversion for bank receipt")
    return min(score, Decimal("0.99")), "; ".join(reasons)


def transfer_row(outflow: dict[str, Any], inflow: dict[str, Any], score: Decimal, reason: str) -> dict[str, Any]:
    out_amt = decimal_field(outflow, "amount") or Decimal("0")
    in_amt = decimal_field(inflow, "amount") or Decimal("0")
    implied_fx = Decimal("1") if outflow.get("currency") == inflow.get("currency") else abs(in_amt / out_amt) if out_amt else Decimal("0")
    status = "confirmed" if score >= HIGH_CONFIDENCE_MIN else "probable"
    transfer_id = stable_id("transfer", outflow.get("transaction_id"), inflow.get("transaction_id"))
    return {
        "transfer_id": transfer_id,
        "owner": outflow.get("owner") or inflow.get("owner") or "samuel",
        "from_transaction_id": outflow.get("transaction_id", ""),
        "to_transaction_id": inflow.get("transaction_id", ""),
        "from_account": account_label(outflow),
        "to_account": account_label(inflow),
        "from_date": outflow.get("date", ""),
        "to_date": inflow.get("date", ""),
        "from_amount": out_amt,
        "from_currency": outflow.get("currency", ""),
        "to_amount": in_amt,
        "to_currency": inflow.get("currency", ""),
        "implied_fx_rate": implied_fx,
        "match_confidence": float(score),
        "match_reason": reason,
        "status": status,
    }


def apply_matches(transactions: list[dict[str, Any]], transfers: list[dict[str, Any]]) -> None:
    by_id = {row.get("transaction_id"): row for row in transactions}
    for transfer in transfers:
        for field in ["from_transaction_id", "to_transaction_id"]:
            tx = by_id.get(transfer.get(field))
            if tx is not None:
                tx["matched_transfer_id"] = transfer["transfer_id"]


def greedy_match(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outflows = [row for row in candidates if (decimal_field(row, "amount") or Decimal("0")) < 0]
    inflows = [row for row in candidates if (decimal_field(row, "amount") or Decimal("0")) > 0]

    potential: list[tuple[Decimal, int, dict[str, Any], dict[str, Any], str]] = []
    for outflow in outflows:
        for inflow in inflows:
            scored = candidate_score(outflow, inflow)
            if scored is None:
                continue
            score, reason = scored
            day_gap = abs((date_field(inflow) - date_field(outflow)).days)  # type: ignore[operator]
            potential.append((score, day_gap, outflow, inflow, reason))

    potential.sort(key=lambda item: (-item[0], item[1], item[2].get("date", ""), item[3].get("date", "")))
    used: set[str] = set()
    transfers: list[dict[str, Any]] = []
    for score, _day_gap, outflow, inflow, reason in potential:
        out_id = outflow.get("transaction_id", "")
        in_id = inflow.get("transaction_id", "")
        if not out_id or not in_id or out_id in used or in_id in used:
            continue
        transfers.append(transfer_row(outflow, inflow, score, reason))
        used.add(out_id)
        used.add(in_id)
    return transfers


def unmatched_large(candidates: list[dict[str, Any]], matched_ids: set[str]) -> list[dict[str, Any]]:
    rows = []
    for row in candidates:
        if row.get("transaction_id") in matched_ids:
            continue
        if is_assumed_one_sided_transfer(row):
            continue
        amount_sgd = decimal_field(row, "amount_sgd")
        amount_original = decimal_field(row, "amount")
        if amount_sgd is not None:
            is_large = abs(amount_sgd) >= LARGE_SGD_REVIEW_THRESHOLD
        elif amount_original is not None:
            is_large = abs(amount_original) >= LARGE_SGD_REVIEW_THRESHOLD
        else:
            is_large = False
        if is_large:
            rows.append(row)
    return rows


def transfer_summary(transfers: list[dict[str, Any]]) -> dict[str, int]:
    by_status = defaultdict(int)
    for row in transfers:
        by_status[row.get("status", "")] += 1
    return dict(by_status)


def run() -> dict[str, Any]:
    ensure_dirs()
    categorized_path = PROCESSED_DIR / "categorized_transactions.csv"
    transactions_path = PROCESSED_DIR / "transactions.csv"
    transactions = read_csv_dicts(categorized_path if categorized_path.exists() else transactions_path)
    candidates = [row for row in transactions if is_candidate(row)]
    transfers = greedy_match(candidates)
    apply_matches(transactions, transfers)
    matched_ids = {row["from_transaction_id"] for row in transfers} | {row["to_transaction_id"] for row in transfers}
    large_unmatched = unmatched_large(candidates, matched_ids)

    write_csv(transactions_path, transactions, TRANSACTION_COLUMNS)
    write_csv(categorized_path, transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "transfers.csv", transfers, TRANSFER_COLUMNS)
    write_csv(PROCESSED_DIR / "unmatched_transfers.csv", large_unmatched, TRANSACTION_COLUMNS)
    return {
        "matched_transfers": len(transfers),
        "transfer_candidates": len(candidates),
        "large_unmatched": len(large_unmatched),
        **{f"{status}_transfers": count for status, count in transfer_summary(transfers).items()},
    }


if __name__ == "__main__":
    print(run())
