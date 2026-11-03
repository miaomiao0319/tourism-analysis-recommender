import json
import unittest
from crawler.sample_collect import HEADERS, parse_entity, parse_html, robots_allows


class SampleParserTests(unittest.TestCase):
    def test_robots_specific_allow_and_default_deny(self):
        rules = 'User-agent: *\nDisallow: /wiki/Special:\nDisallow: /wiki/Special:EntityData/\nAllow: /wiki/Special:EntityData/*.\nDisallow: /w/\n'
        self.assertTrue(robots_allows(rules, 'https://www.wikidata.org/wiki/Special:EntityData/Q2047427.json'))
        self.assertFalse(robots_allows(rules, 'https://www.wikidata.org/wiki/Special:EntityData/Q2047427'))
        self.assertFalse(robots_allows(rules, 'https://www.wikidata.org/w/api.php'))

    def test_target_only_preserves_price(self):
        other = '<table><tr><td>美食</td></tr></table>'
        html = other + '<h2>张家口市区景点一览</h2><table><thead><tr>'
        html += ''.join(f'<th>{v}</th>' for v in HEADERS) + '</tr></thead><tbody>'
        row = '<tr><td>大境门</td><td>桥西区</td><td>免费(20长城)</td><td>1h</td><td>长城</td></tr>'
        html += row * 12 + '</tbody></table>' + other
        result = parse_html(html.encode())
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0]['price_raw'], '免费(20长城)')
        with self.assertRaises(ValueError):
            parse_html(html.replace('门票(元)', '新价格').encode())
        with self.assertRaises(ValueError):
            parse_html(html.replace('<td>1h</td>', '').encode())
        with self.assertRaises(ValueError):
            parse_html((html + '<h2>张家口市区景点一览</h2>').encode())

    def test_wrong_entity_rejected(self):
        with self.assertRaises(KeyError):
            parse_entity(json.dumps({'entities': {}}).encode())


if __name__ == '__main__':
    unittest.main()
