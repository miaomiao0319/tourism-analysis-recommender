import unittest

from cleaning.additional_name_types import TYPE, WETLAND, enrich


class AdditionalNameTypesTests(unittest.TestCase):
    def test_explicit_terms_preserve_existing_types_and_source(self):
        row = {'name': '西溪湿地旅游区', 'type_codes': [], 'source_refs': {'name': ['source']}}
        self.assertTrue(enrich(row))
        self.assertEqual(row['type_codes'], [WETLAND])
        self.assertEqual(row['source_refs']['types'], ['source'])
        town = {'name': '西塘古镇景区', 'type_codes': [], 'source_refs': {'name': ['town']}}
        self.assertTrue(enrich(town))
        self.assertEqual(town['type_codes'], [TYPE])
        self.assertFalse(enrich(town))
        self.assertFalse(enrich({'name': '文化旅游区', 'type_codes': [], 'source_refs': {'name': ['x']}}))


if __name__ == '__main__':
    unittest.main()
