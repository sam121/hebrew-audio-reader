from datetime import date
from decimal import Decimal
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import parse_date, parse_decimal, parse_month_token, parse_yyyymm


class CommonParsingTests(unittest.TestCase):
    def test_parse_wise_date(self):
        self.assertEqual(parse_date("05-02-2026 20:35:19.917"), date(2026, 2, 5))

    def test_parse_ibkr_month(self):
        self.assertEqual(parse_yyyymm("202604"), date(2026, 4, 30))

    def test_parse_dbs_month_token(self):
        start, end = parse_month_token("Apr2026")
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(end, date(2026, 4, 30))

    def test_parse_decimal_with_commas(self):
        self.assertEqual(parse_decimal("1,234.50"), Decimal("1234.50"))


if __name__ == "__main__":
    unittest.main()

