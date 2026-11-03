import unittest
from cleaning.admission_followup import phoenix_quote, URL


class SeasonalEvidenceTests(unittest.TestCase):
    def test_october_uses_peak_and_rejects_incomplete_or_ceiling(self):
        text=URL+" 旺季价格为60元 淡季价格为30元 4月1日至10月31日 2027年12月31日 2025-12-10"
        self.assertEqual(phoenix_quote(text),"60.00")
        for value in (text.replace("10月31日","9月30日"),text+"最高限价",text.replace("2027年12月31日","")):
            with self.assertRaises(ValueError):
                phoenix_quote(value)
