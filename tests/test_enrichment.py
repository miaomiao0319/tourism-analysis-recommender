import unittest

from cleaning.city_reference import CityReference, roman
from cleaning.relation_audit import review
from crawler.ticket_preview import parse
from crawler.voyage_evidence import fee_sections
from cleaning.atlas_clean import build
from cleaning.review_remaining import price_candidates


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

    def test_county_and_town_follow_parent_chain_without_promoting_county(self):
        rows = [dict(code="1301", parentCode="13", level=1, name="甲", pinyin="jia", fullName="甲市"),
                dict(code="130101", parentCode="1301", level=2, name="乙", pinyin="yi", fullName="乙县"),
                dict(code="130101001", parentCode="130101", level=3, name="丙", pinyin="bing", fullName="丙镇"),
                dict(code="469001", parentCode="46", level=1, name="五指山", pinyin="wu zhi shan", fullName="五指山市")]
        reference = CityReference(rows, dict(url="https://example.invalid", collected_at="2026-11-01T00:00:00Z"), "test",
                                  {("130000", "yi"), ("130000", "bing"), ("460000", "wuzhishan")}, {("130000", "乙县景区")})
        self.assertEqual(reference.lookup("130000", "Yi", True)[0], "甲市")
        self.assertEqual(reference.lookup("130000", "Bing", True)[0], "甲市")
        self.assertIsNone(reference.lookup("460000", "Wuzhishan", True))
        self.assertEqual(reference.lookup_prefix("130000", "乙县景区")[0], "甲市")
        self.assertIsNone(reference.lookup_prefix("140000", "乙县景区"))

    def test_wikidata_alias_requires_country_and_exact_division_code(self):
        rows = [dict(code="6501", parentCode="65", level=1, name="乌鲁木齐", pinyin="wu lu mu qi", fullName="乌鲁木齐市")]
        meta = dict(url="https://example.invalid", collected_at="2026-11-01T00:00:00Z")
        reference = CityReference(rows, meta, "test")
        claim = lambda v: dict(mainsnak=dict(datavalue=dict(value=v)))
        entity = dict(id="Q16959", labels=dict(en=dict(value="Ürümqi")), aliases={},
                      claims=dict(P17=[claim(dict(id="Q148"))], P442=[claim("65 01")]))
        reference.add_wikidata(entity, meta, "test/Q16959.json", {("650000", "Ürümqi")})
        self.assertEqual(reference.lookup("650000", "Ürümqi", True)[0], "乌鲁木齐市")
        self.assertIsNone(reference.lookup("150000", "Ürümqi", True))
        entity["claims"]["P17"] = [claim(dict(id="Q30"))]
        with self.assertRaises(ValueError):
            reference.add_wikidata(entity, meta, "test", {("650000", "Ürümqi")})

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

    def test_gateway_city_is_not_attraction_location(self):
        from test_atlas_clean import fixtures
        tables, requests = fixtures()
        rows, _, _, mappings, _, issues, _ = build(tables, requests, "test", "test_batch")
        aid = next(r["attraction_id"] for r in mappings if r["publisher_identity"] == "atlas:different-id")
        record = next(r for r in rows if r["attraction_id"] == aid)
        self.assertEqual(record["city_key"], "")
        self.assertIn("gateway_city_not_verified_attraction_location", issues[aid])

    def test_fee_section_keeps_transport_and_old_date_separate_from_next_section(self):
        body = '<h2>Fees and permits</h2><p>Adult ticket (Sep 2022): ¥220.</p><p>Bus ¥90.</p><h2>Sleep</h2><p>Room ¥500.</p>'
        rows = fee_sections(body.encode())
        self.assertEqual(len(rows), 1)
        self.assertIn("Sep 2022", rows[0]["text"])
        self.assertNotIn("500", rows[0]["text"])

    def test_dated_adult_quotes_never_become_current_eligible_prices(self):
        section = dict(text="Entrance ticket (Sep 2022): Adult: Peak ¥220, off-peak ¥80. Bus ¥90.",
            source_url="https://en.wikivoyage.org/wiki/Jiuzhaigou_Nature_Reserve", raw_ref="a.raw", revision_id="1")
        rows = price_candidates([section])
        self.assertEqual([r["amount"] for r in rows], ["220.00", "80.00"])
        self.assertTrue(all(not r["budget_eligible"] and r["price_policy_id"] is None for r in rows))
        self.assertTrue(all(r["source_date"] == "2022-09" for r in rows))
        section["text"] = section["text"].replace("Sep 2022", "today")
        with self.assertRaises(ValueError):
            price_candidates([section])
