import unittest

from cleaning.city_reference import CityReference, roman
from cleaning.relation_audit import review
from crawler.ticket_preview import parse


class EnrichmentTests(unittest.TestCase):
    def test_province_bound_pinyin_and_aliases(self):
        rows = [dict(code="1411", parentCode="14", level=1, name="吕梁", pinyin="lv liang", fullName="吕梁市"),
                dict(code="5132", parentCode="51", level=1, name="阿坝", pinyin="a ba", fullName="阿坝藏族羌族自治州"),
                dict(code="469001", parentCode="46", level=1, name="五指山", pinyin="wu zhi shan", fullName="五指山市"),
                dict(code="2202", parentCode="22", level=1, name="吉林市", pinyin="ji lin shi", fullName="吉林市")]
        reference = CityReference(rows, dict(url="https://example.invalid", collected_at="2026-11-01T00:00:00Z"), "data/raw/test")
        self.assertEqual(roman("Xi'an"), "xian")
        self.assertEqual(reference.lookup("140000", "Lüliang", True)[0], "吕梁市")
        self.assertIsNone(reference.lookup("130000", "Lüliang", True))
        self.assertEqual(reference.lookup("510000", "阿坝州")[0], "阿坝藏族羌族自治州")
        self.assertIsNone(reference.lookup("460000", "Wuzhishan", True))
        self.assertEqual(reference.lookup("220000", "Jilin", True)[0], "吉林市")
        self.assertEqual(reference.lookup("220000", "吉林")[0], "吉林市")
        self.assertEqual(len(reference.evidence), 3)

    def test_ambiguous_reference_never_picks_first(self):
        rows = [dict(code=code, parentCode="13", level=1, name=name, pinyin="same", fullName=name + "市")
                for code, name in [("1301", "甲"), ("1302", "乙")]]
        reference = CityReference(rows, dict(url="https://example.invalid", collected_at="2026-11-01T00:00:00Z"), "test")
        self.assertIsNone(reference.lookup("130000", "Same", True))

    def test_ticket_original_text_and_non_ticket_table(self):
        body = '<h2>门票</h2><table><tr><th>名称</th><th>门票(元)</th></tr><tr><td>甲</td><td>免费(登楼另付)</td></tr></table><table><tr><th>名称</th><th>住宿</th></tr><tr><td>乙</td><td>200</td></tr></table>'
        result = parse(body.encode())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price_raw"], "免费(登楼另付)")
        self.assertEqual(parse('<table><tr><th>消费档次</th><th>门票活动</th></tr><tr><td>经济型</td><td>50-100</td></tr></table>'.encode()), [])
        with self.assertRaises(ValueError):
            parse(body.replace('<td>免费(登楼另付)</td>', '').encode())

    def test_combined_destination_is_not_confirmed_duplicate(self):
        mapping = [dict(attraction_id="a", name_aliases=["山与湖"], source_refs=["x"]),
                   dict(attraction_id="b", name_aliases=["山景区"], source_refs=["y"])]
        evidence = [dict(source_ref="x", source_id="atlas_featured", raw={}),
                    dict(source_ref="y", source_id="atlas_5a", raw=dict(name_zh="山景区"))]
        record = review([["a", "b"]], mapping, evidence)[0]
        self.assertEqual(record["triage"], "combined_destination_scope_warning")
        self.assertFalse(record["confirmed_same_entity"])
