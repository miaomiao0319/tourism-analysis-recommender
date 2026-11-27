"""Create a new batch with the reviewed 2026 Taishan admission price."""
import csv
import json
from datetime import datetime, timezone

from cleaning.admission_followup import expanded_price
from cleaning.admission_pilot import POLICY, load_rows, read_lines, sha
from cleaning.atlas_clean import FIELDS, ROOT, dump_json, dump_lines, validate
from database.preflight import check

PARENT = 'atlas_clean_20261125_01'
BATCH = 'atlas_clean_20261125_02'
ATTRACTION = 'atl_13acc630a7ec824c2aa752e84a567a3e5112384f1a380c31'
HTML_URL = 'https://tsgw.taian.gov.cn/art/2025/4/7/art_77180_5653044.html'
PDF_URL = 'https://fgw.taian.gov.cn/module/download/downfile.jsp?classid=0&filename=f75c028507394f478031ecb97a965bc2.pdf'
HTML_SHA = '4abdf68e085ff8b3655ce878b31ed2ff6025d301e3f45b96e8c19782d7be2d9e'
PDF_SHA = '58256296d77821fc95850034af03e1488efc8b0bb8a598470494f8de1fd98384'


def price_validator(row, evidence, dictionaries):
    if row['attraction_id'] != ATTRACTION:
        return expanded_price(row, evidence, dictionaries)
    expected = ('exact', '115.00', '115.00', 'CNY', POLICY)
    if tuple(row[k] for k in ('price_form', 'price_min', 'price_max', 'currency', 'price_policy_id')) != expected:
        raise ValueError('Invalid Taishan admission price')
    if len([p for p in dictionaries['price_policies'] if p['id'] == POLICY and p['currency'] == 'CNY' and p.get('approval_ref')]) != 1:
        raise ValueError('Approved price policy missing')
    refs = row['source_refs'].get('price', [])
    by_ref = {e['source_ref']: e for e in evidence}
    if set(refs) != {'e_taishan_notice', 'e_taishan_ticket'} or any(ref not in by_ref for ref in refs):
        raise ValueError('Taishan price evidence missing')
    notice, ticket = by_ref['e_taishan_notice'], by_ref['e_taishan_ticket']
    if (notice['source_url'] != PDF_URL or notice.get('effective_from') != '2024-01-01'
            or notice.get('effective_to') != '2026-12-31' or ticket['source_url'] != HTML_URL):
        raise ValueError('Taishan price evidence does not match the reviewed sources')


def main():
    check(PARENT)
    old = ROOT / 'data/metadata' / PARENT
    raw = ROOT / 'data/raw/taishan_20261125_01'
    if sha(raw / 'ticket.html') != HTML_SHA or sha(raw / 'notice.pdf') != PDF_SHA:
        raise ValueError('Reviewed Taishan source bytes differ')
    manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((old / 'dictionaries.json').read_text(encoding='utf-8'))
    rows = load_rows(ROOT / manifest['standard_file'])
    evidence = read_lines(old / 'evidence.jsonl')
    sources = read_lines(old / 'sources.jsonl')
    collected = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    for ref, source, url, filename, date in (
            ('e_taishan_notice', 'taishan_notice', PDF_URL, 'notice.pdf', '2023-12-29'),
            ('e_taishan_ticket', 'taishan_ticket', HTML_URL, 'ticket.html', '2025-04-07')):
        sources.append(dict(source_id=source, name='泰山景区政府公开票价资料', base_url=url,
                            coverage='山东泰安市泰山景区', collection_basis='公开网页和行政票价通知',
                            redistribution_status='unknown', notes='记录价格事实及出处；原文保留本机'))
        evidence.append(dict(source_ref=ref, source_id=source, source_item_id=None, source_url=url,
                             collected_at=collected, source_date=date, source_date_kind='published',
                             raw_ref=(raw / filename).relative_to(ROOT).as_posix(),
                             effective_from='2024-01-01' if ref == 'e_taishan_notice' else None,
                             effective_to='2026-12-31' if ref == 'e_taishan_notice' else None))
    matches = [row for row in rows if row['attraction_id'] == ATTRACTION]
    if len(matches) != 1 or matches[0]['name'] != '泰安市泰山景区' or matches[0]['price_form'] != 'unknown':
        raise ValueError('Unexpected Taishan entity or existing price')
    for row in rows:
        row['batch_id'] = BATCH
    target = matches[0]
    target.update(price_form='exact', price_min='115.00', price_max='115.00', currency='CNY',
                  price_policy_id=POLICY, price_basis='普通全价基础门票；不含交通和索道',
                  price_raw='泰山门票115元/人，首次检票后三日内有效', collected_at=collected)
    target['source_refs']['price'] = ['e_taishan_notice', 'e_taishan_ticket']
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT, created_at=collected)
    for key in ('raw_count', 'accepted_source_count', 'merged_extra_count'):
        manifest[key] += 2
    manifest['quality']['unknown_price_count'] -= 1
    manifest['quality']['comparable_price_count'] += 1
    manifest['quality']['notes'].append('Taishan scenic-area full admission verified for October 2026; linked mountain entity remains separate')
    for path in [ROOT / manifest['standard_file'], *(old / n for n in
            ('manifest.json', 'dictionaries.json', 'evidence.jsonl', 'sources.jsonl', 'entity-map.jsonl')),
            raw / 'notice.pdf', raw / 'ticket.html']:
        manifest['raw_inputs'].append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    validate(rows, evidence, dictionaries, manifest, price_validator)
    output, processed = ROOT / 'data/metadata' / BATCH, ROOT / 'data/processed' / BATCH
    if output.exists() or processed.exists():
        raise FileExistsError('Immutable batch exists')
    output.mkdir()
    processed.mkdir()
    target_file = processed / 'attractions.csv'
    with target_file.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if key in ('type_codes', 'source_refs')
                             else value for key, value in row.items()})
    dump_json(output / 'dictionaries.json', dictionaries)
    dump_lines(output / 'sources.jsonl', sources)
    dump_lines(output / 'evidence.jsonl', evidence)
    dump_lines(output / 'entity-map.jsonl', read_lines(old / 'entity-map.jsonl'))
    manifest.update(standard_file=target_file.relative_to(ROOT).as_posix(), standard_sha256=sha(target_file),
                    dictionaries_sha256=sha(output / 'dictionaries.json'))
    validate(load_rows(target_file), evidence, dictionaries, manifest, price_validator)
    dump_json(output / 'manifest.json', manifest)
    print(json.dumps({'batch_id': BATCH, 'comparable_prices': manifest['quality']['comparable_price_count']}))


if __name__ == '__main__':
    main()
