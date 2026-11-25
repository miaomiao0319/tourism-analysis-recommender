"""Derive traceable heritage types from explicit names in a new snapshot."""
import csv
import json
from datetime import datetime, timezone

from cleaning.admission_followup import expanded_price
from cleaning.admission_pilot import load_rows, read_lines, sha
from cleaning.atlas_clean import FIELDS, ROOT, dump_json, dump_lines, validate
from database.preflight import check

PARENT = 'atlas_clean_20261102_02'
BATCH = 'atlas_clean_20261125_01'
TYPE = 'name_heritage_explicit'
TERMS = ('古城', '博物馆', '纪念馆', '遗址')
TYPE_DEFINITION = dict(code=TYPE, label='历史文化遗产（名称规则）',
    definition='名称明确包含古城、博物馆、纪念馆或遗址的景点',
    method='rule', basis='根据来源记录的景点名称识别明确类别词；不推断开放状态或其他类型')


def inferred(row):
    return not row['type_codes'] and any(term in row['name'] for term in TERMS)


def main():
    check(PARENT)
    old = ROOT / 'data/metadata' / PARENT
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((old / 'dictionaries.json').read_text(encoding='utf-8'))
    rows = load_rows(ROOT / manifest['standard_file'])
    evidence = read_lines(old / 'evidence.jsonl')
    dictionaries['types'].append(TYPE_DEFINITION)
    changed = []
    for row in rows:
        row['batch_id'] = BATCH
        if inferred(row):
            row['type_codes'] = [TYPE]
            row['source_refs']['types'] = list(row['source_refs']['name'])
            changed.append(row['attraction_id'])
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT,
                    created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    manifest['quality']['missing_type_count'] = sum(not row['type_codes'] for row in rows)
    manifest['quality']['notes'].append('Explicit name rule adds heritage categories; source names are retained as evidence')
    for path in [ROOT / manifest['standard_file'], *(old / n for n in
            ('manifest.json', 'dictionaries.json', 'evidence.jsonl', 'sources.jsonl', 'entity-map.jsonl'))]:
        manifest['raw_inputs'].append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    validate(rows, evidence, dictionaries, manifest, expanded_price)
    output = ROOT / 'data/metadata' / BATCH
    processed = ROOT / 'data/processed' / BATCH
    if output.exists() or processed.exists():
        raise FileExistsError('Immutable batch exists')
    output.mkdir()
    processed.mkdir()
    target = processed / 'attractions.csv'
    with target.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if key in ('type_codes', 'source_refs')
                             else value for key, value in row.items()})
    dump_json(output / 'dictionaries.json', dictionaries)
    for name in ('sources.jsonl', 'evidence.jsonl', 'entity-map.jsonl'):
        dump_lines(output / name, read_lines(old / name))
    manifest.update(standard_file=target.relative_to(ROOT).as_posix(), standard_sha256=sha(target),
                    dictionaries_sha256=sha(output / 'dictionaries.json'))
    validate(load_rows(target), evidence, dictionaries, manifest, expanded_price)
    dump_json(output / 'manifest.json', manifest)
    print(json.dumps(dict(batch_id=BATCH, changed_count=len(changed),
                          missing_type_count=manifest['quality']['missing_type_count']), ensure_ascii=False))


if __name__ == '__main__':
    main()
