"""Resolve Qianling's city from archived CC0 geographic entities."""
import csv
import json
from datetime import datetime, timezone

from cleaning.admission_pilot import load_rows, read_lines, sha
from cleaning.atlas_clean import FIELDS, ROOT, dump_json, dump_lines, validate
from cleaning.official_price_20261126 import price_validator
from database.preflight import check

PARENT = 'atlas_clean_20261126_01'
BATCH = 'atlas_clean_20261126_02'
ATTRACTION = 'atl_00360a409f5ec168bd73e6a0e8e95692467a0a1efffa92fd'
CITY = 'CN:610000:28e7e2d5835c4908e95b51e445e592fecc006ab542ac2da6'
RAW = 'data/raw/qianling_wikidata_20261126_02'
HASHES = {'Q950653': 'd76ec3382c4d92ca2278f7275c4dd1488947394d492a1a64794bacee4439eaa7',
          'Q1201675': '0b077b1adca885baf8964e6650e4d1a7f70dfd3cc5b22740f7edd874bf5009e4'}
REFS = ['e_qianling_wd', 'e_qian_county_wd']


def verify_entities(root):
    raw = root / RAW
    run = json.loads((raw / 'run.json').read_text(encoding='utf-8'))
    requests = {item['url'].rsplit('/', 1)[-1].replace('.json', ''): item for item in run['requests']}
    if run['status'] != 'success':
        raise ValueError('Incomplete Wikidata acquisition')
    entities = {}
    for qid, expected in HASHES.items():
        path = raw / (qid + '.raw')
        if sha(path) != expected or requests[qid]['sha256'] != expected:
            raise ValueError('Wikidata source mismatch')
        entities[qid] = json.loads(path.read_text(encoding='utf-8'))['entities'][qid]
        if entities[qid]['modified'] > '2026-10-31T23:59:59Z':
            raise ValueError('Wikidata snapshot postdates data cutoff')
    def targets(entity, rank):
        return [s['mainsnak']['datavalue']['value']['id'] for s in entity['claims']['P131']
                if s['rank'] == rank and 'P582' not in s.get('qualifiers', {})]
    if (entities['Q950653']['labels']['en']['value'] != 'Qianling Mausoleum'
            or entities['Q1201675']['labels']['zh']['value'] != '乾县'
            or targets(entities['Q950653'], 'normal') != ['Q1201675']
            or targets(entities['Q1201675'], 'preferred') != ['Q497341']):
        raise ValueError('Wikidata location chain mismatch')
    return requests


def main():
    check(PARENT)
    requests = verify_entities(ROOT)
    old, raw = ROOT / 'data/metadata' / PARENT, ROOT / RAW
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((old / 'dictionaries.json').read_text(encoding='utf-8'))
    rows = load_rows(ROOT / manifest['standard_file'])
    evidence = read_lines(old / 'evidence.jsonl')
    entity_map = read_lines(old / 'entity-map.jsonl')
    linked = [e.get('raw', {}) for e in evidence if e['source_ref'] == 'e_5a_311']
    if len(linked) != 1 or linked[0].get('atlas_id') != 'qianling-mausoleum' or linked[0].get('prefecture') != '咸阳市':
        raise ValueError('Atlas scenic-area linkage does not support the city')
    mapping = [m for m in entity_map if m['attraction_id'] == ATTRACTION]
    if len(mapping) != 1 or mapping[0]['publisher_identity'] != 'atlas:qianling-mausoleum':
        raise ValueError('Atlas entity identity mismatch')
    for qid, ref in zip(('Q950653', 'Q1201675'), REFS):
        request = requests[qid]
        evidence.append(dict(source_ref=ref, source_id='wikidata_geography', source_item_id=qid,
            source_url=request['url'], collected_at=request['collected_at'],
            source_date=None, source_date_kind='unknown', raw_ref=RAW + '/' + qid + '.raw',
            record_role='geographic_reference'))
    candidates = [row for row in rows if row['attraction_id'] == ATTRACTION]
    if len(candidates) != 1 or candidates[0]['name'] != '乾陵' or candidates[0]['city_key']:
        raise ValueError('Unexpected Qianling entity')
    for row in rows:
        row['batch_id'] = BATCH
    row = candidates[0]
    row.update(city_key=CITY, city_name='咸阳市',
               collected_at=max(row['collected_at'], *(requests[qid]['collected_at'] for qid in HASHES)))
    row['source_refs']['location'] = sorted(set(row['source_refs']['location']) | set(REFS) | {'d_6104', 'e_5a_311'})
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT,
                    created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    for key in ('raw_count', 'accepted_source_count', 'merged_extra_count'):
        manifest[key] += 2
    manifest['quality']['missing_city_count'] -= 1
    manifest['quality']['issue_counts']['city_unresolved'] -= 1
    manifest['quality']['notes'].append('Qianling location supported by CC0 Wikidata county chain and linked Atlas scenic-area prefecture; gateway city excluded')
    for path in [ROOT / manifest['standard_file'], *(old / n for n in
            ('manifest.json', 'dictionaries.json', 'evidence.jsonl', 'sources.jsonl', 'entity-map.jsonl')),
            raw / 'run.json', raw / 'license.raw', raw / 'robots.raw', *(raw / (qid + '.raw') for qid in HASHES)]:
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
        for item in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if key in ('type_codes', 'source_refs')
                             else value for key, value in item.items()})
    dump_json(output / 'dictionaries.json', dictionaries)
    dump_lines(output / 'sources.jsonl', read_lines(old / 'sources.jsonl'))
    dump_lines(output / 'evidence.jsonl', evidence)
    dump_lines(output / 'entity-map.jsonl', entity_map)
    manifest.update(standard_file=target.relative_to(ROOT).as_posix(), standard_sha256=sha(target),
                    dictionaries_sha256=sha(output / 'dictionaries.json'))
    validate(load_rows(target), evidence, dictionaries, manifest, price_validator)
    dump_json(output / 'manifest.json', manifest)
    print(json.dumps({'batch_id': BATCH, 'missing_city_count': manifest['quality']['missing_city_count']}))


if __name__ == '__main__':
    main()
