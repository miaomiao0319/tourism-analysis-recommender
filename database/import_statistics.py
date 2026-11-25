"""Validate and atomically import statistics for an existing loading batch."""
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from analysis.common import canonical_json, hdfs_cat, parse_jsonl, source_context, valid_id
from analysis.mapreduce.converter import convert_output
from cleaning.atlas_clean import FIELDS, ROOT
from database.import_batch import equal_attractions, equal_evidence
from database.preflight import check, json_lines
from database.statistics_check import (
    SCOPES, check_data_quality, check_overall_price_histogram,
    check_overall_price_summary, check_pending_price_policy, check_required_count_groups,
    dimension_key, reconcile_counts, validate_run_identity,
)


def check_run_details(run, engine, batch_id, input_uri, output_uri):
    command = run.get('execution')
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError('Missing run command')
    try:
        start = datetime.fromisoformat(run['started_at'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(run['finished_at'].replace('Z', '+00:00'))
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError('Invalid run timestamps')
    except (KeyError, TypeError, AttributeError):
        raise ValueError('Missing or invalid run timestamps') from None
    if engine == 'mapreduce':
        app = run.get('yarn_application_id')
        if not isinstance(app, str) or not re.fullmatch(r'application_[0-9]+_[0-9]+', app):
            raise ValueError('Invalid YARN application ID')
        required = (('-input', input_uri), ('-output', output_uri))
        if 'mapreduce.framework.name=yarn' not in command:
            raise ValueError('MapReduce command does not use YARN')
    else:
        required = (('--batch-id', batch_id), ('--input-uri', input_uri), ('--output-uri', output_uri))
    pairs = list(zip(command, command[1:]))
    if any(pairs.count(pair) != 1 or command.count(pair[0]) != 1 for pair in required):
        raise ValueError('Run command does not match input or output')


def validate_statistics(batch_id, results_root):
    check(batch_id)
    metadata = ROOT / 'data/metadata' / batch_id
    manifest = json.loads((metadata / 'manifest.json').read_text(encoding='utf-8'))
    dictionaries = json.loads((metadata / 'dictionaries.json').read_text(encoding='utf-8'))
    with (ROOT / manifest['standard_file']).open(encoding='utf-8', newline='') as stream:
        raw_rows = list(csv.DictReader(stream))
    rows = [dict(row, type_codes=json.loads(row['type_codes'])) for row in raw_rows]
    hdfs = str(Path(os.environ['HADOOP_HOME']) / 'bin/hdfs')
    context = source_context(hdfs, os.environ.get('HDFS_ROOT', '/tourism'), batch_id,
                             os.environ.get('HDFS_URI', 'hdfs://localhost:9000'))
    if context['manifest'] != manifest or context['dictionaries'] != dictionaries:
        raise ValueError('HDFS metadata differs from local validated metadata')
    records, runs = {}, {}
    for engine in ('mapreduce', 'spark_sql'):
        folder = Path(results_root) / batch_id / engine
        runs[engine] = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
        run = runs[engine]
        valid_id(run['run_id'])
        output = context['hdfs_batch'] + '/runs/' + run['run_id'] + '/' + engine + '/raw'
        if (run.get('status') != 'succeeded' or run.get('data_kind') != manifest['data_kind']
                or run.get('dictionaries_sha256') != manifest['dictionaries_sha256']
                or run.get('input_uri') != context['paths']['input']
                or run.get('metadata_uri') != context['paths']['manifest']
                or run.get('raw_output_uri') != output
                or run.get('standard_count') != len(rows)):
            raise ValueError('Run metadata does not match verified input or output')
        check_run_details(run, engine, batch_id, context['paths']['input'], output)
        selected = parse_jsonl((folder / 'statistics.jsonl').read_text(encoding='utf-8'), batch_id, engine)
        raw = hdfs_cat(hdfs, output + '/part-*').decode('utf-8')
        actual = convert_output(raw, batch_id) if engine == 'mapreduce' else parse_jsonl(raw, batch_id, engine)
        if sorted(map(canonical_json, selected)) != sorted(map(canonical_json, actual)):
            raise ValueError('HDFS raw output differs from selected results')
        records[engine] = selected
    mr, spark = records['mapreduce'], records['spark_sql']
    validate_run_identity(manifest, runs['mapreduce'], runs['spark_sql'])
    reconcile_counts(mr, spark, batch_id, len(rows))
    check_required_count_groups(rows, mr, spark, batch_id)
    check_data_quality(rows, spark, batch_id)
    types = Counter()
    for row in rows:
        for code in row['type_codes'] or [None]:
            types[dimension_key({'scope': 'type', 'country_code': row['country_code'], 'type_code': code})] += 1
    type_records = [r for r in spark if r['metric'] == 'attraction_count' and r['dimensions'].get('scope') == 'type']
    if {dimension_key(r['dimensions']): r['value']['count'] for r in type_records} != types:
        raise ValueError('Type counts differ from standard rows')
    groups = {'all': {dimension_key({'scope': 'all'}): {'scope': 'all'}}, 'city': {}, 'grade': {}}
    for row in rows:
        for scope in ('city', 'grade'):
            group = {'scope': scope}
            for field in SCOPES[scope] - {'scope'}:
                group[field] = (row[field] or None) if field in ('city_key', 'grade_level') else row[field]
            groups[scope][dimension_key(group)] = group
    prices = [r for r in spark if r['metric'] in ('price_summary', 'price_histogram')]
    policies = dictionaries['price_policies']
    if policies:
        identities = {(p['currency'], p['id']) for p in policies}
        if len(identities) != len(policies):
            raise ValueError('Duplicate price policy')
        for currency, policy in identities:
            for scope in groups.values():
                for group in scope.values():
                    check_overall_price_summary(rows, prices, batch_id, currency, policy, group)
                    check_overall_price_histogram(rows, prices, batch_id, currency, policy, group)
        expected = 2 * len(identities) * sum(map(len, groups.values()))
    else:
        for metric in ('price_summary', 'price_histogram'):
            check_pending_price_policy(prices, batch_id, metric, policies)
        expected = 2
    if len(prices) != expected or any(r['metric'] not in ('attraction_count', 'data_quality', 'price_summary', 'price_histogram') for r in mr + spark):
        raise ValueError('Unexpected statistics records')
    if any(r['metric'] != 'attraction_count' or r['dimensions']['scope'] not in ('city', 'grade') for r in mr):
        raise ValueError('Unexpected MapReduce metric')
    return manifest, dictionaries, raw_rows, records


def import_records(connection, batch_id, manifest, dictionaries, raw_rows, records):
    expected = {}
    for row in records['mapreduce'] + records['spark_sql']:
        key = (row['engine'], row['metric'], dimension_key(row['dimensions']))
        if key in expected:
            raise ValueError('Duplicate statistics key')
        expected[key] = (row['dimensions'], row['status'], row['value'])
    encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False)
    metadata = ROOT / 'data/metadata' / batch_id
    sources = json_lines(metadata / 'sources.jsonl')
    evidence = json_lines(metadata / 'evidence.jsonl')
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION'")
            cursor.execute('SELECT contract_version,standard_sha256,manifest_json,dictionaries_json,sources_json,state FROM dataset_batches WHERE batch_id=%s FOR UPDATE', (batch_id,))
            batch = cursor.fetchone()
            if not batch or batch[0:2] != (manifest['contract_version'], manifest['standard_sha256']) or json.loads(batch[2]) != manifest or json.loads(batch[3]) != dictionaries or json.loads(batch[4]) != sources or batch[5] not in ('loading', 'ready'):
                raise ValueError('Missing or inconsistent batch')
            cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM attractions WHERE batch_id=%s', (batch_id,))
            if not equal_attractions(raw_rows, cursor.fetchall()):
                raise ValueError('Stored attractions differ from validated snapshot')
            cursor.execute('SELECT source_ref,source_id,source_item_id,source_url,collected_at,source_date,source_date_kind,raw_ref,payload_json FROM source_records WHERE batch_id=%s', (batch_id,))
            if not equal_evidence(evidence, cursor.fetchall()):
                raise ValueError('Stored evidence differs from validated snapshot')
            cursor.execute('SELECT engine,metric,dimension_key,dimensions_json,status,value_json FROM analysis_results WHERE batch_id=%s', (batch_id,))
            stored = cursor.fetchall()
            if stored:
                existing = {(r[0], r[1], r[2]): (json.loads(r[3]), r[4], json.loads(r[5]) if r[5] is not None else None) for r in stored}
                if existing != expected:
                    raise ValueError('Existing statistics differ; never overwrite')
                connection.rollback()
                return {'batch_id': batch_id, 'repeated': True, 'count': len(expected), 'state': batch[5]}
            if batch[5] != 'loading':
                raise ValueError('Cannot add statistics to a ready batch')
            values = [(batch_id, *key, encode(value[0]), value[1], encode(value[2]) if value[2] is not None else None) for key, value in expected.items()]
            cursor.executemany('INSERT INTO analysis_results (batch_id,engine,metric,dimension_key,dimensions_json,status,value_json) VALUES (%s,%s,%s,%s,%s,%s,%s)', values)
            cursor.execute('SELECT engine,metric,dimension_key,dimensions_json,status,value_json FROM analysis_results WHERE batch_id=%s', (batch_id,))
            stored = {(r[0], r[1], r[2]): (json.loads(r[3]), r[4], json.loads(r[5]) if r[5] is not None else None) for r in cursor.fetchall()}
            if stored != expected:
                raise ValueError('Imported statistics differ on readback')
        connection.commit()
        return {'batch_id': batch_id, 'repeated': False, 'count': len(expected), 'state': 'loading'}
    except Exception:
        connection.rollback()
        raise


def run(batch_id, results_root):
    import pymysql
    manifest, dictionaries, rows, records = validate_statistics(batch_id, results_root)
    user, password = os.environ.get('DB_IMPORT_USER'), os.environ.get('DB_IMPORT_PASSWORD')
    if not user or password is None:
        raise ValueError('Set DB_IMPORT_USER and DB_IMPORT_PASSWORD')
    options = dict(user=user, password=password, database=os.environ.get('DB_NAME', 'tourism_recommender'), charset='utf8mb4', autocommit=False)
    if os.environ.get('DB_UNIX_SOCKET'):
        options['unix_socket'] = os.environ['DB_UNIX_SOCKET']
    else:
        options.update(host=os.environ.get('DB_HOST', '127.0.0.1'), port=int(os.environ.get('DB_PORT', '3306')))
    connection = pymysql.connect(**options)
    try:
        return import_records(connection, batch_id, manifest, dictionaries, rows, records)
    finally:
        connection.close()


if __name__ == '__main__':
    print(json.dumps(run(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=2))
