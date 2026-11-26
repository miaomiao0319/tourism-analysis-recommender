"""Apply four reviewed 2026 admission notices to an immutable snapshot."""
import csv
import json
from datetime import datetime, timezone
from html.parser import HTMLParser

from cleaning.admission_pilot import POLICY, load_rows, read_lines, sha
from cleaning.atlas_clean import FIELDS, ROOT, dump_json, dump_lines, validate
from cleaning.taishan_admission import price_validator as previous_price_validator
from crawler.price_sources_20261126 import URLS
from database.preflight import check

PARENT = 'atlas_clean_20261125_03'
BATCH = 'atlas_clean_20261126_01'
RAW = 'data/raw/official_price_20261126_01'
NOTICES = {
    'beijing': dict(id='atl_0a747b98cf730e75768ec21921dd065d3ba90322a101d1e0',
        name='北京世界公园', amount='0.00', form='free', date='2026-09-17',
        valid_from='2026-07-12', valid_to='2026-12-31',
        basis='普通游客免基础入园票；演出和游乐项目另计',
        tokens=('北京世界公园', '免大门票', '2026年12月31日', '7月12日', '另行付费'),
        digest='f14502623cbf4ed05cb840033ba4403f5630d8b41353ff70faeac1122d25bac2'),
    'linyi': dict(id='atl_3201fac09c0d95d21350d04cd37ffc3c63e86569cd2fb3a3',
        name='临沂动植物园', amount='45.00', form='exact', date='2026-09-18',
        valid_from='2026-10-01', valid_to='2029-09-30',
        basis='普通全价基础门票；特殊人群优惠另计',
        tokens=('临沂动植物园', '每人次45元', '2026年10月1日', '2029年9月30日'),
        digest='a0f10f98c1f06c14e344ef87ac64184ae766e93865baaebb1f4cc99be9c653c1'),
    'yichun': dict(id='atl_4e366d242b72edc047de08553a9d7c35bed81c5eadbcb973',
        name='透龙山', amount='45.00', form='exact', date='2026-02-13',
        valid_from='2026-08-20', valid_to='2027-12-31',
        basis='普通全价基础门票；5月1日至10月31日旺季价格',
        tokens=('透龙山景区', '5月1日-10月31日', '每人次45元', '2026年8月20日', '2027年12月31日'),
        digest='63ffa23145478d4cdcc2b5ccb3cb6327a6bb994bfed95c067d91678d47a916c9'),
    'pingliang': dict(id='atl_a14be0541a4ca71a1e447d7b0b2ecbd6f1eb2225c90ff206',
        name='平凉市崆峒山风景名胜区', amount='110.00', form='exact', date='2026-03-30',
        valid_from='2026-04-01', valid_to='2026-10-31',
        basis='普通全价旺季基础门票；景区交通另计',
        tokens=('崆峒山景区', '2026年4月1日', '10月31日', '全价门票：110元/人', '景区交通'),
        digest='c93bf17373e2e9267f62a2a117057a745e94c74875c7c47181878accc96f095b'),
}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data.strip())


def source_text(path, notice):
    if sha(path) != notice['digest']:
        raise ValueError('Reviewed notice bytes differ')
    parser = Text()
    parser.feed(path.read_text(encoding='utf-8'))
    text = ''.join(parser.parts)
    if any(token not in text for token in notice['tokens']):
        raise ValueError('Notice price, dates or ticket scope changed')


def price_validator(row, evidence, dictionaries):
    matching = [(key, value) for key, value in NOTICES.items() if value['id'] == row['attraction_id']]
    if not matching:
        return previous_price_validator(row, evidence, dictionaries)
    key, notice = matching[0]
    if tuple(row[k] for k in ('name', 'price_form', 'price_min', 'price_max', 'currency', 'price_policy_id')) != (
            notice['name'], notice['form'], notice['amount'], notice['amount'], 'CNY', POLICY):
        raise ValueError('Reviewed price does not match the source')
    if len([p for p in dictionaries['price_policies'] if p['id'] == POLICY and p['currency'] == 'CNY' and p.get('approval_ref')]) != 1:
        raise ValueError('Approved price policy missing')
    refs = row['source_refs'].get('price', [])
    if refs != ['e_notice_' + key]:
        raise ValueError('Price evidence reference missing')
    matching_evidence = [e for e in evidence if e['source_ref'] == refs[0]]
    if (len(matching_evidence) != 1 or matching_evidence[0]['source_url'] != URLS[key]
            or matching_evidence[0].get('effective_from') != notice['valid_from']
            or matching_evidence[0].get('effective_to') != notice['valid_to']):
        raise ValueError('Price evidence does not match reviewed notice')


def main():
    check(PARENT)
    old, raw = ROOT / 'data/metadata' / PARENT, ROOT / RAW
    run = json.loads((raw / 'run.json').read_text(encoding='utf-8'))
    requests = {item['name']: item for item in run['requests']}
    if run['status'] != 'success' or set(requests) != set(NOTICES):
        raise ValueError('Incomplete acquisition run')
    for key, notice in NOTICES.items():
        request = requests[key]
        if request['url'] != URLS[key] or request['sha256'] != notice['digest']:
            raise ValueError('Acquisition record differs from reviewed notice')
        source_text(raw / (key + '.html'), notice)
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((old / 'dictionaries.json').read_text(encoding='utf-8'))
    rows = load_rows(ROOT / manifest['standard_file'])
    evidence = read_lines(old / 'evidence.jsonl')
    sources = read_lines(old / 'sources.jsonl')
    created = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    for key, notice in NOTICES.items():
        request = requests[key]
        source_id, ref = 'notice_' + key, 'e_notice_' + key
        sources.append(dict(source_id=source_id, name=notice['name'] + '公开票价材料',
            base_url=URLS[key], coverage=notice['name'], collection_basis='公开票价材料',
            redistribution_status='unknown', notes='政府网站公开资料；原文留在本机，保留票价事实及出处'))
        evidence.append(dict(source_ref=ref, source_id=source_id, source_item_id=None,
            source_url=URLS[key], collected_at=request['collected_at'], source_date=notice['date'],
            source_date_kind='published', raw_ref=RAW + '/' + key + '.html',
            effective_from=notice['valid_from'], effective_to=notice['valid_to']))
        matches = [row for row in rows if row['attraction_id'] == notice['id']]
        if len(matches) != 1 or matches[0]['name'] != notice['name'] or matches[0]['price_form'] != 'unknown':
            raise ValueError('Unexpected entity or existing price: ' + key)
        row = matches[0]
        row.update(price_form=notice['form'], price_min=notice['amount'], price_max=notice['amount'],
                   currency='CNY', price_policy_id=POLICY, price_basis=notice['basis'],
                   price_raw=notice['basis'], collected_at=request['collected_at'])
        row['source_refs']['price'] = [ref]
    for row in rows:
        row['batch_id'] = BATCH
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT, created_at=created)
    for key in ('raw_count', 'accepted_source_count', 'merged_extra_count'):
        manifest[key] += len(NOTICES)
    manifest['quality']['unknown_price_count'] -= len(NOTICES)
    manifest['quality']['comparable_price_count'] += len(NOTICES)
    manifest['quality']['notes'].append('Four reviewed 2026 admission notices, including free entry; no transport or activities included')
    for path in [ROOT / manifest['standard_file'], *(old / n for n in
            ('manifest.json', 'dictionaries.json', 'evidence.jsonl', 'sources.jsonl', 'entity-map.jsonl')),
            raw / 'run.json', *(raw / (name + '.html') for name in NOTICES),
            *(raw / (name + '-robots.txt') for name in NOTICES)]:
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
    dump_lines(output / 'sources.jsonl', sources)
    dump_lines(output / 'evidence.jsonl', evidence)
    dump_lines(output / 'entity-map.jsonl', read_lines(old / 'entity-map.jsonl'))
    manifest.update(standard_file=target.relative_to(ROOT).as_posix(), standard_sha256=sha(target),
                    dictionaries_sha256=sha(output / 'dictionaries.json'))
    validate(load_rows(target), evidence, dictionaries, manifest, price_validator)
    dump_json(output / 'manifest.json', manifest)
    print(json.dumps({'batch_id': BATCH, 'comparable_prices': manifest['quality']['comparable_price_count']}))


if __name__ == '__main__':
    main()
