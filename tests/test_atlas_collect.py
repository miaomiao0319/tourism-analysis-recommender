import unittest

from crawler.atlas_collect import coverage, read_csv


class AtlasTests(unittest.TestCase):
    def test_csv_preserves_quoted_comma_and_multiline(self):
        rows = read_csv('id,name_zh,city\r\na,"景点,甲","城市\n原文"\r\n'.encode(), ["id", "name_zh"])
        self.assertEqual(rows[0]["name_zh"], "景点,甲")
        self.assertEqual(rows[0]["city"], "城市\n原文")
        for text in ["id,id\na,b\n", "id,name_zh\na,b,c\n", "id,name_zh\na\n", "id,name_zh\n"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_csv(text.encode(), ["id", "name_zh"])

    def test_counts_keep_duplicates_and_regions_separate(self):
        base = dict(id="same", name_zh="同名景点", city="原始城市", designations="national", verified="2026-10-28")
        rows = [dict(base, region_id=code) for code in ["110000", "110000", "120000", "810000"]]
        stats = coverage(rows)
        self.assertEqual(stats["total_source_rows"], 4)
        self.assertEqual(stats["mainland_source_rows"], 3)
        self.assertEqual(stats["covered_target_regions"], 2)
        self.assertEqual(stats["other_region_counts"], {"810000": 1})
        self.assertEqual(stats["duplicate_id_observations"], 3)
        self.assertEqual(len(rows), 4)
        self.assertFalse(stats["cleaning_executed"])
        rows[0]["designations"] = "5A; 4A"
        stats = coverage(rows)
        self.assertEqual(stats["mainland_scenic_label_rows"], 1)
        self.assertEqual(stats["both_4a_and_5a_label_rows"], 1)


if __name__ == "__main__":
    unittest.main()
