"""Constructed test data only; never real source policy or ticket data."""
import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cleaning.atlas_clean import build, clean, dump_json, validate


def site(sid, name="同名景点", code="130000", city="SourceCity", grade="4A"):
    return dict(id=sid, name_zh=name, region_id=code, city=city,
                category="nature", designations=grade, verified="2026-10-20")


def fixtures():
    tables = {"sites": [site("a", " 景点\n甲 "), site("b"), site("c", code="140000"),
                         site("outside", code="810000")],
              "featured": [site("different-id", city="SourceCity")],
              "5a": [dict(mct_id="m1", atlas_id="a", name_zh="景点 甲", region_id="130000", prefecture="甲市")]}
    requests = {kind: dict(url="https://example.invalid/" + kind, collected_at="2026-11-01T00:00:00Z") for kind in tables}
    return tables, requests


class AtlasCleaningTests(unittest.TestCase):
    def test_explicit_merge_conflict_alias_and_same_name_preservation(self):
        tables, requests = fixtures()
        original = copy.deepcopy(tables)
        rows, evidence, excluded, mapping, dictionaries, issues, suspected = build(tables, requests, "data/raw/test", "test_batch")
        self.assertEqual(tables, original)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(evidence), 6)
        self.assertEqual(len(excluded), 1)
        merged = next(r for r in rows if r["name"] == "景点 甲")
        self.assertEqual(merged["grade_status"], "conflict")
        self.assertEqual(merged["grade_level"], "")
        self.assertEqual(merged["city_name"], "甲市")
        # b and different-id share a name and location but remain two entities.
        same_name = [r for r in rows if r["name"] == "同名景点"]
        self.assertEqual(len(same_name), 3)
        self.assertEqual(len(suspected), 1)
        self.assertEqual(len(suspected[0]), 2)
        for row in rows:
            self.assertEqual(row["price_form"], "unknown")
            self.assertEqual(row["price_min"], "")
        other_province = next(r for r in rows if r["province_name"] == "山西")
        self.assertEqual(other_province["city_name"], "")
        self.assertEqual(dictionaries["price_policies"], [])

    def test_identity_survives_name_change_and_order(self):
        tables, requests = fixtures()
        before = build(tables, requests, "data/raw/test", "batch1")[3]
        tables["sites"].reverse()
        next(r for r in tables["sites"] if r["id"] == "b")["name_zh"] = "新名称"
        after = build(tables, requests, "data/raw/test", "batch2")[3]
        get_ids = lambda records: {r["publisher_identity"]: r["attraction_id"] for r in records}
        self.assertEqual(get_ids(before), get_ids(after))

    def test_conflicting_province_link_stops(self):
        tables, requests = fixtures()
        tables["5a"][0]["region_id"] = "140000"
        with self.assertRaisesRegex(ValueError, "conflicting provinces"):
            build(tables, requests, "data/raw/test", "test_batch")

    def test_link_to_broader_destination_does_not_merge(self):
        tables, requests = fixtures()
        tables["sites"][0]["name_zh"] = "整个大峡谷"
        tables["5a"][0]["name_zh"] = "峡谷内部景区"
        rows, evidence, excluded, mapping, dictionaries, issues, suspected = build(tables, requests, "data/raw/test", "test_batch")
        self.assertEqual(len(rows), 5)
        self.assertTrue({"整个大峡谷", "峡谷内部景区"} <= {r["name"] for r in rows})
        self.assertEqual(len(suspected), 2)

    def test_ambiguous_crosswalk_stays_unknown(self):
        tables, requests = fixtures()
        tables["5a"].append(dict(mct_id="m2", atlas_id="b", name_zh="同名景点", region_id="130000", prefecture="乙市"))
        rows = build(tables, requests, "data/raw/test", "test_batch")[0]
        unresolved = next(r for r in rows if r["name"] == "同名景点" and r["province_name"] == "河北" and r["grade_level"] == "4A")
        self.assertEqual(unresolved["city_key"], "")

    def test_roundtrip_integrity_and_overwrite_protection(self):
        tables, requests = fixtures()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "data/raw/fixture"
            raw.mkdir(parents=True)
            run = dict(status="success", data_kind="test", requests=[], files={})
            hashes = {}
            for kind, rows in tables.items():
                path = raw / (kind + ".raw")
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                hashes[kind] = hashlib.sha256(path.read_bytes()).hexdigest()
                run["requests"].append(dict(requests[kind], raw_ref=path.name, sha256=hashes[kind]))
                run["files"][kind] = dict(row_count=len(rows))
            dump_json(raw / "run.json", run)
            manifest = clean(raw, "test_batch", root)
            self.assertEqual((manifest["raw_count"], manifest["accepted_source_count"], manifest["merged_extra_count"], manifest["standard_count"]), (6, 5, 1, 4))
            self.assertEqual(manifest["data_kind"], "test")
            for kind in tables:
                self.assertEqual(hashlib.sha256((raw / (kind + ".raw")).read_bytes()).hexdigest(), hashes[kind])
            data = (root / manifest["standard_file"]).read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertEqual(len(data.splitlines()), 5)
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["standard_sha256"])
            with self.assertRaises(FileExistsError):
                clean(raw, "test_batch", root)
            (raw / "sites.raw").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                clean(raw, "new_batch", root)

    def test_validator_rejects_price_and_evidence_tampering(self):
        tables, requests = fixtures()
        rows, evidence, excluded, mapping, dictionaries, issues, suspected = build(tables, requests, "data/raw/test", "test_batch")
        manifest = dict(raw_count=6, excluded_count=1, accepted_source_count=5, merged_extra_count=1, standard_count=4)
        validate(rows, evidence, dictionaries, manifest)
        rows[0]["price_min"] = "0.00"
        with self.assertRaisesRegex(ValueError, "cannot justify a price"):
            validate(rows, evidence, dictionaries, manifest)
        rows[0]["price_min"] = ""
        rows[0]["source_refs"]["name"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            validate(rows, evidence, dictionaries, manifest)


if __name__ == "__main__":
    unittest.main()
