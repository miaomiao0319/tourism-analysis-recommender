import json
import unittest
from html import escape

from cleaning.targeted_followup import GOV_URL, government_quote, glass_quote
from crawler.listing_evidence import Listings, metres


class TargetedTests(unittest.TestCase):
    def test_pricing_notice_keeps_component_scope_and_dates(self):
        source = GOV_URL + ' 临发改价格 2026-10-01 2029-09-30 沂蒙山龟蒙景区门票70元/人'
        row = government_quote(source)
        self.assertEqual(row['amount'], '70.00')
        self.assertEqual(row['effective_from'], '2026-10-01')
        self.assertIsNone(row['attraction_id'])
        self.assertFalse(row['budget_eligible'])
        with self.assertRaises(ValueError):
            government_quote(source.replace('2029-09-30', 'unknown'))

    def test_museum_extracts_main_building_not_combo(self):
        source = 'Shanghai Museum of Glass (上海玻璃博物馆), 685 West Changjiang Road. ¥60 for entry to the main museum building; combo ¥180. (updated Jul 2026) ## Do'
        row = glass_quote(source)
        self.assertEqual(row['amount'], '60.00')
        self.assertIsNone(row['effective_to'])
        self.assertFalse(row['budget_eligible'])
        with self.assertRaises(ValueError):
            glass_quote(source.replace('updated Jul 2026', 'updated Apr 2019'))

    def test_template_parameters_and_coordinate_distance(self):
        payload = {'parts': [{'template': {'target': {'wt': 'see'}, 'params': {'name': {'wt': 'Museum'}, 'price': {'wt': '¥60'}, 'lastedit': {'wt': '2026-07-01'}}}}]}
        parser = Listings()
        parser.feed('<bdi data-mw="' + escape(json.dumps(payload), quote=True) + '"></bdi>')
        self.assertEqual(parser.rows[0]['params']['price'], '¥60')
        self.assertTrue(300 < metres(31.3457,121.4673,31.343784,121.470188) < 500)
        self.assertGreater(metres(31.3457,121.4673,30,120), 500)
