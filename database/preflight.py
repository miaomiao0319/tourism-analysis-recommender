"""Validate the current real batch before any database operation.

Run: python -m database.preflight atlas_clean_20261102_02
This command is read-only and does not claim an import or database connection.
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from cleaning.atlas_clean import FIELDS, ROOT, validate
from cleaning.admission_followup import expanded_price


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def check(batch_id, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
        raise ValueError("Invalid batch identifier")
    root = root.resolve()
    metadata = root / "data/metadata" / batch_id
    manifest = json.loads((metadata / "manifest.json").read_text(encoding="utf-8"))
    if manifest["batch_id"] != batch_id or manifest["contract_version"] != "1.0":
        raise ValueError("Manifest identity or contract version mismatch")
    standard = (root / manifest["standard_file"]).resolve()
    expected_path = root / "data/processed" / batch_id / "attractions.csv"
    if standard != expected_path or digest(standard) != manifest["standard_sha256"]:
        raise ValueError("Standard path or SHA-256 mismatch")
    dictionary_path = metadata / "dictionaries.json"
    if digest(dictionary_path) != manifest["dictionaries_sha256"]:
        raise ValueError("Dictionary SHA-256 mismatch")
    for item in manifest["raw_inputs"]:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or digest(path) != item["sha256"]:
            raise ValueError("Input path or SHA-256 mismatch")
    dictionaries = json.loads(dictionary_path.read_text(encoding="utf-8"))
    evidence = json_lines(metadata / "evidence.jsonl")
    sources = json_lines(metadata / "sources.jsonl")
    source_ids = [s["source_id"] for s in sources]
    if len(source_ids) != len(set(source_ids)) or any(e["source_id"] not in source_ids for e in evidence):
        raise ValueError("Duplicate or unregistered source")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x) for x in source_ids):
        raise ValueError("Invalid source identifier")
    with standard.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("CSV field order mismatch")
        rows = list(reader)
    for row in rows:
        if row["batch_id"] != batch_id:
            raise ValueError("Mixed batch identifiers")
        row["source_refs"] = json.loads(row["source_refs"])
        row["type_codes"] = json.loads(row["type_codes"])
    # This source-specific validator supports the two reviewed prices only.
    if batch_id != "atlas_clean_20261102_02":
        raise ValueError("A new batch needs its own reviewed price validator")
    validate(rows, evidence, dictionaries, manifest, expanded_price)
    return dict(batch_id=batch_id, standard_count=len(rows), evidence_count=len(evidence),
                sources_count=len(sources), input_count=len(manifest["raw_inputs"]),
                comparable_prices=sum(bool(r["price_policy_id"]) for r in rows),
                database_connected=False, imported=False)


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), ensure_ascii=False, indent=2))
