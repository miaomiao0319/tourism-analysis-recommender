import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database.preflight import check
from database.import_batch import utc, attraction_values, equal_attractions, equal_evidence
from cleaning.atlas_clean import FIELDS
import json


class DatabasePreflightTests(unittest.TestCase):
    def test_repeat_checks_contents_not_only_counts(self):
        row = dict.fromkeys(FIELDS, "")
        row.update(batch_id="test", attraction_id="A", name="景点", collected_at="2026-10-01T00:00:00Z", type_codes="[]", source_refs='{"name":["e"]}')
        stored = list(attraction_values(row))
        for field in ("type_codes", "source_refs"):
            i = FIELDS.index(field)
            stored[i] = json.dumps(stored[i])
        self.assertTrue(equal_attractions([row], [stored]))
        stored[FIELDS.index("name")] = "不同景点"
        self.assertFalse(equal_attractions([row], [stored]))
        e = dict(source_ref="e", source_id="s", source_item_id=None, source_url="https://example.invalid", collected_at="2026-10-01T00:00:00Z", source_date=None, source_date_kind="unknown", raw_ref="raw")
        record = ("e", "s", None, e["source_url"], utc(e["collected_at"]), None, "unknown", "raw", json.dumps(e))
        self.assertTrue(equal_evidence([e], [record]))
        self.assertFalse(equal_evidence([e], [record[:-1] + (json.dumps(dict(e, raw_ref="changed")),)]))

    def test_timestamps_convert_to_utc_and_naive_times_fail(self):
        self.assertEqual(utc("2026-11-02T08:00:00+08:00").isoformat(), "2026-11-02T00:00:00")
        with self.assertRaises(ValueError):
            utc("2026-11-02T08:00:00")

    def test_batch_id_cannot_escape_workspace(self):
        with TemporaryDirectory() as directory:
            for value in ("../outside", "other/batch", ""):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    check(value, Path(directory))
