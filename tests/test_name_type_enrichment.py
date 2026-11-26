import unittest

from cleaning.name_type_enrichment import inferred


class NameTypeEnrichmentTests(unittest.TestCase):
    def test_rule_requires_empty_type_and_explicit_name(self):
        self.assertTrue(inferred({'name': '平遥古城景区', 'type_codes': []}))
        self.assertTrue(inferred({'name': '伪满皇宫博物馆', 'type_codes': []}))
        self.assertFalse(inferred({'name': '泰山', 'type_codes': []}))
        self.assertFalse(inferred({'name': '平遥古城', 'type_codes': ['atlas_city']}))


if __name__ == '__main__':
    unittest.main()
