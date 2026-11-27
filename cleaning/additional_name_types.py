"""Extend explicit-name type rules in a new immutable snapshot."""
import csv
import json
from datetime import datetime, timezone

from cleaning.admission_pilot import load_rows, read_lines, sha
from cleaning.atlas_clean import FIELDS, ROOT, dump_json, dump_lines, validate
from cleaning.name_type_enrichment import TYPE
from cleaning.taishan_admission import price_validator
from database.preflight import check

PARENT = 'atlas_clean_20261125_02'
BATCH = 'atlas_clean_20261125_03'
HERITAGE_TERMS = ('古镇', '古村', '石窟')
WETLAND = 'name_wetland_explicit'
WETLAND_DEFINITION = dict(code=WETLAND, label='湿地（名称规则）',
    definition='名称明确包含湿地的景点', method='rule',
    basis='根据来源记录的景点名称识别湿地；不推断生态保护级别或开放状态')


def update_dictionaries(dictionaries):
    heritage = next(item for item in dictionaries['types'] if item['code'] == TYPE)
    heritage['definition'] = '名称明确包含古城、古镇、古村、石窟、博物馆、纪念馆或遗址的景点'
    dictionaries['types'].append(WETLAND_DEFINITION)


def enrich(row):
    if row['type_codes']:
        return False
    types = []
    if any(term in row['name'] for term in HERITAGE_TERMS):
        types.append(TYPE)
    if '湿地' in row['name']:
        types.append(WETLAND)
    if not types:
        return False
    row['type_codes'] = sorted(types)
    row['source_refs']['types'] = list(row['source_refs']['name'])
    return True


def main():
    check(PARENT)
    old = ROOT / 'data/metadata' / PARENT
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((old / 'dictionaries.json').read_text(encoding='utf-8'))
    rows = load_rows(ROOT / manifest['standard_file'])
    evidence = read_lines(old / 'evidence.jsonl')
    update_dictionaries(dictionaries)
    changed = 0
    for row in rows:
        row['batch_id'] = BATCH
        changed += enrich(row)
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT,
                    created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    manifest['quality']['missing_type_count'] = sum(not row['type_codes'] for row in rows)
    manifest['quality']['notes'].append('Explicit name rule extends heritage to ancient towns, villages and grottoes and adds wetland type')
    for path in [ROOT / manifest['standard_file'], *(old / n for n in
            ('manifest.json', 'dictionaries.json', 'evidence.jsonl', 'sources.jsonl', 'entity-map.jsonl'))]:
        manifest['raw_inputs'].append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    validate(rows, evidence, dictionaries, manifest, price_validator)
    output, processed = ROOT / 'data/metadata' / BATCH, ROOT / 'data/processed' / BATCH
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
    validate(load_rows(target), evidence, dictionaries, manifest, price_validator)
    dump_json(output / 'manifest.json', manifest)
    print(json.dumps(dict(batch_id=BATCH, changed_count=changed,
                          missing_type_count=manifest['quality']['missing_type_count'])))


if __name__ == '__main__':
    main()
