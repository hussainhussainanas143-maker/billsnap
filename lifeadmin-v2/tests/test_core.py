import datetime as dt
import unittest

import core


class CoreTests(unittest.TestCase):
    def test_add_months_clamps(self):
        self.assertEqual(core.add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))
        self.assertEqual(core.add_months(dt.date(2026, 3, 14), 24), dt.date(2028, 3, 14))

    def test_pick_stage(self):
        want = {45: None, 31: None, 30: 30, 8: 30, 7: 7, 2: 7, 1: 1, 0: 0, -1: None}
        for dl, s in want.items():
            self.assertEqual(core.pick_stage(dl), s, dl)

    def test_parse_add(self):
        d = core.parse_add_command("add Prestige Mixer | Reliance | 14/03/2026 | 24 | 4,999")
        n = core.normalize_item(d)
        self.assertEqual(n["expiry_date"], "2028-03-14")
        self.assertEqual(n["amount"], 4999.0)

    def test_parse_add_errors(self):
        for bad in ("add x | y", "add Mixer | R | notadate | 12", "add Mixer | R | 2026-03-14 | abc"):
            with self.assertRaises(ValueError):
                core.parse_add_command(bad)

    def test_assess(self):
        ok = {"name": "TV", "purchase_date": "2026-03-14", "warranty_months": 24, "confidence": 0.9}
        self.assertEqual(core.assess_extraction(ok)[0], "ok")
        self.assertEqual(core.assess_extraction({**ok, "confidence": 0.5})[0], "unsure")
        self.assertEqual(core.assess_extraction({"name": "Earbuds", "purchase_date": "2026-11-18", "confidence": 0.9})[0], "missing")
        self.assertEqual(core.assess_extraction({"name": None, "confidence": 0})[0], "empty")


if __name__ == "__main__":
    unittest.main()
