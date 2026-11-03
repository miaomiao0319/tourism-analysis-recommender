"""Preliminary cross-engine count reconciliation; never changes batch state.

This is one necessary check, not a complete statistics validation or importer.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


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


def check_overall_price_summary(standard_rows, spark_records, batch_id, currency, policy_id):
    """Check one overall summary; callers verify the policy and input provenance."""
    if not isinstance(currency, str) or not currency or not isinstance(policy_id, str) or not policy_id:
        raise ValueError('A verified currency and policy are required')
    candidate_count = 0
    prices = []
    for row in standard_rows:
        if row.get('batch_id') != batch_id:
            raise ValueError('Mixed standard batch')
        candidate_count += 1
        if (row.get('price_policy_id') != policy_id or row.get('currency') != currency
                or row.get('price_form') not in ('free', 'exact')):
            continue
        try:
            amount = Decimal(row['price_min'])
            upper = Decimal(row['price_max'])
        except (KeyError, TypeError, InvalidOperation):
            raise ValueError('Invalid comparable amount') from None
        if (not amount.is_finite() or not upper.is_finite() or amount != upper
                or amount < 0 or amount.as_tuple().exponent < -2
                or (row['price_form'] == 'free' and amount != 0)
                or (row['price_form'] == 'exact' and amount <= 0)):
            raise ValueError('Invalid comparable amount')
        prices.append(amount)
    dims = {'scope': 'all', 'currency': currency, 'price_policy_id': policy_id}
    matches = [r for r in spark_records if r.get('metric') == 'price_summary' and r.get('dimensions') == dims]
    if len(matches) != 1:
        raise ValueError('Expected exactly one overall price summary')
    record = matches[0]
    valid_count = len(prices)
    coverage = (format((Decimal(valid_count) / Decimal(candidate_count)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP), '.6f')
                if candidate_count else None)
    def money(value):
        return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')
    expected = {'candidate_count': candidate_count, 'valid_count': valid_count, 'coverage': coverage,
                'min': money(min(prices)) if prices else None, 'max': money(max(prices)) if prices else None,
                'mean': money(sum(prices) / valid_count) if prices else None}
    value = record.get('value')
    if (record.get('batch_id') != batch_id or record.get('engine') != 'spark_sql'
            or record.get('status') != ('ok' if prices else 'no_data') or not isinstance(value, dict)
            or set(value) != set(expected) or type(value['candidate_count']) is not int
            or type(value['valid_count']) is not int or value != expected):
        raise ValueError('Price summary disagrees with standard rows')
    return {'batch_id': batch_id, 'price_summary_reconciliation': 'passed', 'ready_for_import': False}
