from __future__ import annotations

from collections import Counter
from typing import Any

from common import CONFIG_DIR, EXPORTS_DIR, PROCESSED_DIR, TRANSACTION_COLUMNS, ensure_dirs, parse_decimal, read_csv_dicts, write_csv


RULES = [
    ("tax_government", "tax_government", ["hmrc", "iras", "cpf", "income tax", "property tax", "student loan repay", "slc receipts", "student loan", "axs pte ltd", " giro | itx ", " itx "]),
    ("investment", "investment_transaction", ["supplementary retirement scheme", "uob kay hian", "investment & securities", "buy fund", "fund mgt", "hargreaveslansdown", "fixed deposit/structured deposit", "fixed deposits", "outstanding placements", "debit | vanguard", "deb | vanguard", "fpo | vanguard", "direct debit to vanguard collectio"]),
    ("transfer", "internal_or_payment", ["autopay", "bill payment", "payment received", "funds transfer", "fast payment", "remittance transfer", "paynow transfer", "giro payments / collections via giro", "giro standing instruction", ": i-bank", "advice | 0120", "advice | 120-", "received from", "payment to", "sent money to", "moved ", " debit | conversion", " credit | conversion", "bcard freedom", "vanguard asset man", "mysavings/posb saye", "to msa:", "advice fast collection", "giro return", "lloyds bank plc", "bp | lloyds", "revolut", "ocbc singapore", "paypal *fk.aluko", "tfr | a partington", "fpo | a partington", "fpo | amy partington", "fpo | laura corry", "fpo | hazel partington", "fpo | mrs laura beaver", "fpo | louise kelly"]),
    ("fees", "bank_fx_fees", ["account fee", "non-gbp trans fee", "non-gbp purch fee", "assets service fee", "wise charges"]),
    ("insurance", "insurance", ["aviva rcpts accoun", "aviva", "etiqa insurance"]),
    ("housing", "rent_mortgage_property", ["your mortgage", "dd | halifax", "halifax |", "landlords tax serv", "mortgage", "newman & company", "ref: rent", "ref:rent", "rental deposit", "rent 06-01", "rent 0601", "0601 rent", "rent one north", "sandon st rent", "deduction rent payment", "rental payment"]),
    ("transport", "public_transport", ["bus/mrt", "mrt", "comfort/citycab", "taxi", "spl auto topup", "simplygo", "tfl travel", "tfl.gov", "ratp", "mta*nyct", "sncf", "velib", "transit singapore", "cross-country trains"]),
    ("rides_hailing", "grab_uber", ["grab", "grb*", "www.grab.com", "grab ios", "uber", "ubr*"]),
    ("travel", "flights_hotels_holidays", ["emirates", "singapore airlines", "singaporeair", "singaporerlines", "singapore618", "singapore243", "singaporeehb", "british a", "britishai", "british airways", "easyjet", "ryanair", "united 800-932-2732", "united ai", "finnair", "gulf air", "zipair", "flyscoot", "jetstar", "vueling", "transavia", "air france", "eurostar", "bangkok aays", "etihad", "eithad", "marriott", "hotel", "radisson", "resor", "phuket", "airbnb", "booking.com", "vfs (singapore)", "getnomad.app", "centerparcs", "travel reservation", "shangri la", "shangri-la", "citadines", "montcalm", "st pancras renaiss", "hlt stakis", "vrbo", "mountkinabalu", "sixt", "europcar", "arnold clark hire", "sofitel", "adagio paris", "klook travel", "cars on booking", "banyan tree", "the scarlet singapore", "mbs front office", "rent plus s.r.o.", "12 avenue des", "smartecarteireland", "viator", "singpaore flights", "singapore flights"]),
    ("food_dining", "cafes_restaurants", ["coffee", "ya kun", "jimmy monkey", "violet oon", "deliveroo", "guzman", "ristorante", "bistro", "toast", "gelatiamo", "sedap", "one fattened calf", "wong", "restaurant", "bakery", "cafe", "food", "gails", "pret a manger", "koufu", "sushi", "mcdonald", "starbucks", "super simple", "ijooz", "lilians", "mercato metropolitano", "petitsplatsmarc", "les negociants", "victus catering", "red dot at dcis", "tst*", "bar & cooker", "machiya", "maranto", "candlenut", "thekitchin", "the english house", "ce la vi", "spruce", "darjeeling social", "fbh_landingpoint", "lushplatters", "roots@onenorth", "miznon"]),
    ("groceries", "groceries", ["cold storage", "fairprice", "market", "general provisions", "turtle mart", "provisions", "franprix", "monop", "picard", "carrefour", "sainsburys", "tesco", "marks&spencer", "ntuc fp", "fp xtra", "familymart", "sq *grocery post", "redmart"]),
    ("utilities", "utilities_telco", ["sp digital", "circles.life", "singtel", "starhub", "m1 ", "utilities"]),
    ("utilities", "mobile_phone", ["giffgaff", "la poste telecom"]),
    ("subscriptions_software", "software_media_services", ["openai", "chatgpt", "google", "audible", "netflix", "spotify", "elevenlabs", "linkedin", "nintendo", "patreon", "vox media", "the neoliberal project", "persuasion", "stratechery", "dithering", "simplepoli", "economist"]),
    ("business_services", "freelance_tools", ["upwork"]),
    ("charity_donations", "charity_donations", ["effective altruism", "fondation insead", "gofundme"]),
    ("education", "education_childcare", ["dyslexiaaction", "happy fish swim school", "old millhillians club", "cambridge spark", "little bunnies", "cabantac", "miguelita cabantac", "lily | july salary", "lily | august salary", "lily | december salary", "lily | late salary", "to: lily | salary", "to: lily | annual bonus", "to: lily | scholarship"]),
    ("shopping", "retail_gifts", ["apple", "amazon", "amzn", "digital gadgets", "pret-t2", "moonpig", "notonthehighstreet", "mothercare", "takashimaya", "printler.com", "ikea", "lululemon", "beloved bumps", "samsung electron", "courts -", "challenger", "www.asos.com", "next online", "montblanc", "h samuel", "the clarks shop", "sistic", "rodalink", "owndays", "withjoy.com", "lazada sg"]),
    ("health", "health_medical", ["doctor", "clinic", "hospital", "guardian", "watsons", "women's spec cli", "mllim", "mark loh paediatrics", "phoenixrehabgroup", "edge heathcare", "dental", "podiatry", "azure dental", "one-north dental", "vets now", "spire healthcare", "spire hand centre", "ghc genetics", "kkh-self payment", "phoenix rehab", "integrative medical"]),
    ("fitness_wellness", "fitness_wellness", ["sports direct fitn", "methodx", "train with be", "pilates", "little gym", "yunomori", "rascals party and play", "toomanytrees coaching", "k.star@", "hom yoga", "peak performance ventures"]),
    ("religion_community", "religion_community", ["united hebrew"]),
    ("entertainment", "events_entertainment", ["cluequest", "the neutral events"]),
    ("cash_atm", "cash_withdrawal", ["atm cash withdrawal", "cash withdrawal", "la banque postale", "lnk notemachine"]),
]

OVERRIDE_CATEGORIES = {"tax_government", "housing", "education", "fitness_wellness", "religion_community", "travel"}


def load_manual_category_overrides() -> list[dict[str, str]]:
    path = CONFIG_DIR / "manual_category_overrides.yml"
    if not path.exists():
        return []
    overrides: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "manual_category_overrides:":
            continue
        if line.startswith("- "):
            if current:
                overrides.append(current)
            current = {}
            line = line[2:].strip()
            if not line:
                continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        overrides.append(current)
    return overrides


def row_text(row: dict[str, Any]) -> str:
    return " ".join([row.get("description_clean", ""), row.get("description_raw", ""), row.get("merchant", "")]).lower()


def matches_manual_override(row: dict[str, Any], override: dict[str, str]) -> bool:
    for field in ["owner", "date", "institution", "account_id"]:
        expected = override.get(field)
        if expected and str(row.get(field, "")).lower() != expected.lower():
            return False
    snippet = override.get("description_contains", "").lower()
    if snippet and snippet not in row_text(row):
        return False
    expected_amount = parse_decimal(override.get("amount_sgd_abs", ""))
    actual_amount = parse_decimal(row.get("amount_sgd"))
    if expected_amount is not None and actual_amount is not None:
        if abs(abs(actual_amount) - expected_amount) > parse_decimal("0.05"):
            return False
    return True


def apply_manual_override(row: dict[str, Any], overrides: list[dict[str, str]]) -> dict[str, Any] | None:
    for override in overrides:
        if not matches_manual_override(row, override):
            continue
        row["category"] = override.get("category", row.get("category", "uncategorized"))
        row["subcategory"] = override.get("subcategory", row.get("subcategory", "manual_override"))
        row["is_transfer_candidate"] = row["category"] == "transfer"
        row["confidence_status"] = override.get("confidence_status", row.get("confidence_status", "confirmed"))
        return row
    return None


def apply_rules(row: dict[str, Any], overrides: list[dict[str, str]] | None = None) -> dict[str, Any]:
    row["matched_transfer_id"] = ""
    category = (row.get("category") or "uncategorized").strip().lower()
    overrides = overrides or []
    manual_row = apply_manual_override(row, overrides)
    if manual_row:
        return manual_row
    text = row_text(row)
    if "endowus" in text:
        row["category"] = "transfer"
        row["subcategory"] = "assumed_endowus_transfer"
        row["is_transfer_candidate"] = True
        return row
    if row.get("institution") == "ibkr" or "interactive brokers" in text or "interactive br " in text:
        row["category"] = "transfer"
        row["subcategory"] = "assumed_ibkr_transfer"
        row["is_transfer_candidate"] = True
        return row
    if row.get("account_type") == "credit_card" and any(token in text for token in ["payment - dbs internet/wireless", "payment - thank you", "payment received", "auto-pyt from acct"]):
        row["category"] = "transfer"
        row["subcategory"] = "credit_card_repayment"
        row["is_transfer_candidate"] = True
        return row
    if row.get("institution") == "wise" and "topped up account" in text:
        row["category"] = "transfer"
        row["subcategory"] = "wise_top_up"
        row["is_transfer_candidate"] = True
        return row
    if row.get("institution") == "wise" and (" debit | conversion" in text or " credit | conversion" in text or text.startswith("moved ")):
        row["category"] = "transfer"
        row["subcategory"] = "wise_internal_conversion"
        row["is_transfer_candidate"] = True
        return row
    for new_category, subcategory, needles in RULES:
        if new_category in OVERRIDE_CATEGORIES and any(needle in text for needle in needles):
            row["category"] = new_category
            row["subcategory"] = subcategory
            row["is_transfer_candidate"] = False
            return row
    if category and category not in {"uncategorized", "income"}:
        return row
    for new_category, subcategory, needles in RULES:
        if any(needle in text for needle in needles):
            row["category"] = new_category
            row["subcategory"] = subcategory
            if new_category in {"investment", "transfer"}:
                row["is_transfer_candidate"] = True
            return row
    row["category"] = category or "uncategorized"
    return row


def run() -> dict[str, Any]:
    """Lightweight category pass.

    Milestone 1 keeps source categories mostly unchanged. This script exists so
    manual overrides and richer merchant rules can be added without changing the
    pipeline shape later.
    """
    ensure_dirs()
    overrides = load_manual_category_overrides()
    rows = [apply_rules(row, overrides) for row in read_csv_dicts(PROCESSED_DIR / "transactions.csv")]
    counts = Counter(row.get("category", "uncategorized") or "uncategorized" for row in rows)
    write_csv(PROCESSED_DIR / "categorized_transactions.csv", rows, TRANSACTION_COLUMNS)
    write_csv(
        EXPORTS_DIR / "category_summary.csv",
        [{"category": category, "transaction_count": count} for category, count in sorted(counts.items())],
        ["category", "transaction_count"],
    )
    return {"transactions": len(rows), "categories": len(counts)}


if __name__ == "__main__":
    print(run())
