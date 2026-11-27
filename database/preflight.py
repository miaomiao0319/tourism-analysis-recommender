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
    if batch_id not in ("atlas_clean_20261102_02", "atlas_clean_20261125_01", "atlas_clean_20261125_02", "atlas_clean_20261125_03", "atlas_clean_20261126_01", "atlas_clean_20261126_02"):
        raise ValueError("A new batch needs its own reviewed price validator")
    price_validator = expanded_price
    if batch_id in ("atlas_clean_20261125_02", "atlas_clean_20261125_03"):
        from cleaning.taishan_admission import price_validator
    if batch_id in ("atlas_clean_20261126_01", "atlas_clean_20261126_02"):
        from cleaning.official_price_20261126 import price_validator
    validate(rows, evidence, dictionaries, manifest, price_validator)
    if batch_id == "atlas_clean_20261125_01":
        from cleaning.name_type_enrichment import BATCH, PARENT, TYPE, TYPE_DEFINITION, inferred
        check(PARENT, root)
        parent_metadata = root / 'data/metadata' / PARENT
        expected_dictionaries = json.loads((parent_metadata / 'dictionaries.json').read_text(encoding='utf-8'))
        expected_dictionaries['types'].append(TYPE_DEFINITION)
        if (manifest.get('parent_batch_id') != PARENT or dictionaries != expected_dictionaries
                or evidence != json_lines(parent_metadata / 'evidence.jsonl')
                or sources != json_lines(parent_metadata / 'sources.jsonl')):
            raise ValueError('Snapshot metadata differs from the reviewed parent')
        with (root / 'data/processed' / PARENT / 'attractions.csv').open(encoding='utf-8', newline='') as stream:
            previous = list(csv.DictReader(stream))
        if len(previous) != len(rows):
            raise ValueError('Unexpected entity count change')
        for old, new in zip(previous, rows):
            old['type_codes'] = json.loads(old['type_codes'])
            old['source_refs'] = json.loads(old['source_refs'])
            old['batch_id'] = BATCH
            if inferred(old):
                old['type_codes'] = [TYPE]
                old['source_refs']['types'] = list(old['source_refs']['name'])
            if old != new:
                raise ValueError('Snapshot differs from reviewed name rule')
        if manifest['quality']['missing_type_count'] != sum(not row['type_codes'] for row in rows):
            raise ValueError('Type quality count mismatch')
    if batch_id == "atlas_clean_20261125_02":
        from cleaning.taishan_admission import ATTRACTION, BATCH, HTML_SHA, PARENT, PDF_SHA
        from cleaning.admission_pilot import POLICY
        check(PARENT, root)
        parent_metadata = root / 'data/metadata' / PARENT
        if (manifest.get('parent_batch_id') != PARENT
                or dictionaries != json.loads((parent_metadata / 'dictionaries.json').read_text(encoding='utf-8'))
                or evidence[:-2] != json_lines(parent_metadata / 'evidence.jsonl')
                or sources[:-2] != json_lines(parent_metadata / 'sources.jsonl')
                or digest(root / 'data/raw/taishan_20261125_01/ticket.html') != HTML_SHA
                or digest(root / 'data/raw/taishan_20261125_01/notice.pdf') != PDF_SHA):
            raise ValueError('Taishan snapshot metadata or audited source differs')
        with (root / 'data/processed' / PARENT / 'attractions.csv').open(encoding='utf-8', newline='') as stream:
            previous = list(csv.DictReader(stream))
        if len(previous) != len(rows):
            raise ValueError('Unexpected entity count change')
        for old, new in zip(previous, rows):
            old['type_codes'] = json.loads(old['type_codes'])
            old['source_refs'] = json.loads(old['source_refs'])
            old['batch_id'] = BATCH
            if old['attraction_id'] == ATTRACTION:
                old.update(price_form='exact', price_min='115.00', price_max='115.00', currency='CNY',
                           price_policy_id=POLICY, price_basis='普通全价基础门票；不含交通和索道',
                           price_raw='泰山门票115元/人，首次检票后三日内有效', collected_at=manifest['created_at'])
                old['source_refs']['price'] = ['e_taishan_notice', 'e_taishan_ticket']
            if old != new:
                raise ValueError('Snapshot differs from reviewed Taishan change')
        if (manifest['quality']['unknown_price_count'] != sum(r['price_form'] == 'unknown' for r in rows)
                or manifest['quality']['comparable_price_count'] != sum(bool(r['price_policy_id']) for r in rows)):
            raise ValueError('Price quality count mismatch')
    if batch_id == "atlas_clean_20261126_02":
        from cleaning.qianling_city import ATTRACTION, BATCH, CITY, HASHES, PARENT, RAW, REFS, verify_entities
        check(PARENT, root)
        requests = verify_entities(root)
        parent_metadata = root / 'data/metadata' / PARENT
        if (manifest.get('parent_batch_id') != PARENT
                or dictionaries != json.loads((parent_metadata / 'dictionaries.json').read_text(encoding='utf-8'))
                or evidence[:-2] != json_lines(parent_metadata / 'evidence.jsonl')
                or sources != json_lines(parent_metadata / 'sources.jsonl')):
            raise ValueError('Qianling snapshot metadata differs from parent')
        for qid, ref in zip(HASHES, REFS):
            entry = next((item for item in evidence if item['source_ref'] == ref), None)
            if entry != dict(source_ref=ref, source_id='wikidata_geography', source_item_id=qid,
                    source_url=requests[qid]['url'], collected_at=requests[qid]['collected_at'],
                    source_date=None, source_date_kind='unknown', raw_ref=RAW + '/' + qid + '.raw',
                    record_role='geographic_reference'):
                raise ValueError('Qianling evidence differs from acquired Wikidata data')
        with (root / 'data/processed' / PARENT / 'attractions.csv').open(encoding='utf-8', newline='') as stream:
            previous = list(csv.DictReader(stream))
        if len(previous) != len(rows):
            raise ValueError('Unexpected entity count change')
        for old, new in zip(previous, rows):
            old['type_codes'] = json.loads(old['type_codes'])
            old['source_refs'] = json.loads(old['source_refs'])
            old['batch_id'] = BATCH
            if old['attraction_id'] == ATTRACTION:
                old.update(city_key=CITY, city_name='咸阳市',
                           collected_at=max(old['collected_at'], *(requests[q]['collected_at'] for q in HASHES)))
                old['source_refs']['location'] = sorted(set(old['source_refs']['location']) | set(REFS) | {'d_6104', 'e_5a_311'})
            if old != new:
                raise ValueError('Snapshot differs from reviewed Qianling location')
        if manifest['quality']['missing_city_count'] != sum(not row['city_key'] for row in rows):
            raise ValueError('City quality count mismatch')
    if batch_id == "atlas_clean_20261125_03":
        from cleaning.additional_name_types import BATCH, PARENT, enrich, update_dictionaries
        check(PARENT, root)
        parent_metadata = root / 'data/metadata' / PARENT
        expected_dictionaries = json.loads((parent_metadata / 'dictionaries.json').read_text(encoding='utf-8'))
        update_dictionaries(expected_dictionaries)
        if (manifest.get('parent_batch_id') != PARENT or dictionaries != expected_dictionaries
                or evidence != json_lines(parent_metadata / 'evidence.jsonl')
                or sources != json_lines(parent_metadata / 'sources.jsonl')):
            raise ValueError('Snapshot metadata differs from reviewed parent')
        with (root / 'data/processed' / PARENT / 'attractions.csv').open(encoding='utf-8', newline='') as stream:
            previous = list(csv.DictReader(stream))
        if len(previous) != len(rows):
            raise ValueError('Unexpected entity count change')
        for old, new in zip(previous, rows):
            old['type_codes'] = json.loads(old['type_codes'])
            old['source_refs'] = json.loads(old['source_refs'])
            old['batch_id'] = BATCH
            enrich(old)
            if old != new:
                raise ValueError('Snapshot differs from reviewed name rules')
        if manifest['quality']['missing_type_count'] != sum(not row['type_codes'] for row in rows):
            raise ValueError('Type quality count mismatch')
    if batch_id == "atlas_clean_20261126_01":
        from cleaning.official_price_20261126 import BATCH, NOTICES, PARENT, RAW, URLS, source_text
        from cleaning.admission_pilot import POLICY
        check(PARENT, root)
        parent_metadata = root / 'data/metadata' / PARENT
        raw = root / RAW
        run = json.loads((raw / 'run.json').read_text(encoding='utf-8'))
        requests = {item['name']: item for item in run['requests']}
        if (manifest.get('parent_batch_id') != PARENT or run.get('status') != 'success'
                or set(requests) != set(NOTICES)
                or dictionaries != json.loads((parent_metadata / 'dictionaries.json').read_text(encoding='utf-8'))
                or evidence[:-len(NOTICES)] != json_lines(parent_metadata / 'evidence.jsonl')
                or sources[:-len(NOTICES)] != json_lines(parent_metadata / 'sources.jsonl')):
            raise ValueError('Price snapshot metadata differs from reviewed parent')
        for name, notice in NOTICES.items():
            if requests[name]['url'] != URLS[name] or requests[name]['sha256'] != notice['digest']:
                raise ValueError('Price acquisition record mismatch')
            source_text(raw / (name + '.html'), notice)
        with (root / 'data/processed' / PARENT / 'attractions.csv').open(encoding='utf-8', newline='') as stream:
            previous = list(csv.DictReader(stream))
        if len(previous) != len(rows):
            raise ValueError('Unexpected entity count change')
        notices_by_id = {notice['id']: (name, notice) for name, notice in NOTICES.items()}
        for old, new in zip(previous, rows):
            old['type_codes'] = json.loads(old['type_codes'])
            old['source_refs'] = json.loads(old['source_refs'])
            old['batch_id'] = BATCH
            if old['attraction_id'] in notices_by_id:
                name, notice = notices_by_id[old['attraction_id']]
                old.update(price_form=notice['form'], price_min=notice['amount'], price_max=notice['amount'],
                           currency='CNY', price_policy_id=POLICY, price_basis=notice['basis'],
                           price_raw=notice['basis'], collected_at=requests[name]['collected_at'])
                old['source_refs']['price'] = ['e_notice_' + name]
            if old != new:
                raise ValueError('Snapshot differs from reviewed prices')
        if (manifest['quality']['unknown_price_count'] != sum(r['price_form'] == 'unknown' for r in rows)
                or manifest['quality']['comparable_price_count'] != sum(bool(r['price_policy_id']) for r in rows)):
            raise ValueError('Price quality count mismatch')
    return dict(batch_id=batch_id, standard_count=len(rows), evidence_count=len(evidence),
                sources_count=len(sources), input_count=len(manifest["raw_inputs"]),
                comparable_prices=sum(bool(r["price_policy_id"]) for r in rows),
                database_connected=False, imported=False)


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), ensure_ascii=False, indent=2))
