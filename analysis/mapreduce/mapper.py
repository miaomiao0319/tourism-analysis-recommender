"""Hadoop Streaming mapper: one physical CSV line in, two count keys out."""
import argparse
import csv
import json
import sys

# Distributed by -files; standalone on YARN containers.
COLUMNS = 'batch_id,attraction_id,name,country_code,province_key,province_name,city_key,city_name,grade_system,grade_status,grade_level,type_codes,price_form,price_min,price_max,currency,price_basis,price_policy_id,price_raw,source_refs,collected_at'.split(',')


def transform_line(line: str, batch_id: str) -> list[str]:
    try:
        cells = next(csv.reader([line], strict=True))
    except (csv.Error, StopIteration) as exc:
        raise ValueError('Malformed CSV line') from exc
    if cells == COLUMNS:
        return []
    if len(cells) != len(COLUMNS):
        raise ValueError('Expected exactly 21 CSV columns')
    row = dict(zip(COLUMNS, cells))
    if row['batch_id'] != batch_id or not row['attraction_id'] or not row['country_code']:
        raise ValueError('Wrong batch or missing ID/country')
    if row['grade_status'] not in ('rated', 'unrated', 'unknown', 'conflict'):
        raise ValueError('Invalid grade_status')
    if row['grade_status'] != 'rated' and row['grade_level']:
        raise ValueError('Unrated/unknown/conflict grade must not have grade_level')
    dimensions = [
        {'scope': 'city', 'country_code': row['country_code'], 'city_key': row['city_key'] or None},
        {'scope': 'grade', 'country_code': row['country_code'], 'grade_system': row['grade_system'],
         'grade_status': row['grade_status'], 'grade_level': row['grade_level'] or None},
    ]
    return [json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\t1' for d in dimensions]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batch-id', required=True)
    args = p.parse_args()
    for line in sys.stdin:
        if not line.strip():
            raise ValueError('Empty input record')
        if '\r' in line:
            raise ValueError('CR in standard CSV')
        for output in transform_line(line.rstrip('\n'), args.batch_id):
            print(output)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'MAPPER ERROR: {exc}', file=sys.stderr)
        raise
