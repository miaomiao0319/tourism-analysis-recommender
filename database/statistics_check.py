"""Preliminary cross-engine count reconciliation; never changes batch state.

This is one necessary check, not a complete statistics validation or importer.
"""
import hashlib
import json


SCOPES = {
    'city': {'scope', 'country_code', 'city_key'},
    'grade': {'scope', 'country_code', 'grade_system', 'grade_status', 'grade_level'},
}


def dimension_key(dimensions):
    if not isinstance(dimensions, dict) or any(not isinstance(k, str) or not (v is None or isinstance(v, str)) for k, v in dimensions.items()):
        raise ValueError('Dimensions must contain string keys and string/null values')
    serialized = json.dumps(dimensions, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def validate_run_identity(manifest, mapreduce_run, spark_run):
    """Check explicitly named contract fields; not a full run audit."""
    batch = manifest.get('batch_id')
    digest = manifest.get('standard_sha256')
    if not isinstance(batch, str) or not batch or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid batch identity or input SHA-256')
    for run, engine in ((mapreduce_run, 'mapreduce'), (spark_run, 'spark_sql')):
        if (run.get('batch_id') != batch or run.get('engine') != engine
                or run.get('contract_version') != manifest.get('contract_version')
                or run.get('input_sha256') != digest):
            raise ValueError('Run batch, engine, contract or input SHA-256 mismatch')
    return {'batch_id': batch, 'input_identity': 'matched', 'full_run_audit': False}


def count_groups(records, batch_id, engine, scope):
    result = {}
    for row in records:
        if row.get('batch_id') != batch_id or row.get('engine') != engine:
            raise ValueError('Mixed batch or engine')
        if row.get('metric') != 'attraction_count' or row.get('dimensions', {}).get('scope') != scope:
            continue
        dims = row['dimensions']
        if set(dims) != SCOPES[scope] or row.get('status') != 'ok':
            raise ValueError('Invalid count dimensions or status')
        value = row.get('value')
        if not isinstance(value, dict) or set(value) != {'count'} or type(value['count']) is not int or value['count'] < 0:
            raise ValueError('Count must be a nonnegative integer')
        key = dimension_key(dims)
        if key in result:
            raise ValueError('Duplicate statistics dimension')
        result[key] = value['count']
    if not result:
        raise ValueError('Required scope has no count groups')
    return result


def reconcile_counts(mapreduce, spark, batch_id, standard_count):
    if type(standard_count) is not int or standard_count <= 0:
        raise ValueError('Standard count must be positive')
    groups = {}
    for scope in ('city', 'grade'):
        left = count_groups(mapreduce, batch_id, 'mapreduce', scope)
        right = count_groups(spark, batch_id, 'spark_sql', scope)
        if left != right:
            raise ValueError('Cross-engine ' + scope + ' counts disagree')
        if sum(left.values()) != standard_count:
            raise ValueError(scope + ' counts do not reconcile to standard count')
        groups[scope] = len(left)
    return {'batch_id': batch_id, 'count_reconciliation': 'passed', 'group_counts': groups,
            'ready_for_import': False, 'reason': 'Other required metrics, source data, run provenance and database state still need independent validation'}


def check_data_quality(standard_rows, spark_records, batch_id):
    """Compare Spark quality totals with validated rows; verify provenance separately."""
    fields = ('standard_count', 'missing_city_count', 'unknown_grade_count',
              'conflicting_grade_count', 'missing_type_count', 'unknown_price_count',
              'conflicting_price_count')
    expected = dict.fromkeys(fields, 0)
    for row in standard_rows:
        if row.get('batch_id') != batch_id or not isinstance(row.get('type_codes'), list):
            raise ValueError('Invalid standard row batch or type_codes')
        expected['standard_count'] += 1
        expected['missing_city_count'] += row['city_key'] in ('', None)
        expected['unknown_grade_count'] += row['grade_status'] == 'unknown'
        expected['conflicting_grade_count'] += row['grade_status'] == 'conflict'
        expected['missing_type_count'] += not row['type_codes']
        expected['unknown_price_count'] += row['price_form'] == 'unknown'
        expected['conflicting_price_count'] += row['price_form'] == 'conflict'
    quality = [row for row in spark_records if row.get('metric') == 'data_quality']
    if len(quality) != 1:
        raise ValueError('Expected exactly one data quality record')
    row = quality[0]
    value = row.get('value')
    if (row.get('batch_id') != batch_id or row.get('engine') != 'spark_sql'
            or row.get('dimensions') != {'scope': 'all'} or row.get('status') != 'ok'
            or not isinstance(value, dict) or set(value) != set(fields)
            or any(type(value[field]) is not int or value[field] < 0 for field in fields)):
        raise ValueError('Invalid data quality record')
    if value != expected:
        raise ValueError('Data quality counts disagree with standard rows')
    return {'batch_id': batch_id, 'data_quality_reconciliation': 'passed',
            'ready_for_import': False}
