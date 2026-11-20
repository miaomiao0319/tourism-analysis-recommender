"""Actual PySpark SQL job reading immutable HDFS standard CSV and writing HDFS JSONL.

This entrypoint must be run with spark-submit; import is dependency-free for unit checks.
All aggregates originate in Spark, not a Python/Pandas reconstruction.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP

# Distributed via spark-submit --py-files (analysis package) or project PYTHONPATH.
from analysis.common import COLUMNS, COUNT_DIMENSIONS, count_dimensions, json_line, record


def decimal_2(value):
    return str(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def price_coverage(numerator, denominator):
    if not denominator:
        return None
    return str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))


def histogram(prices):
    """Histogram from Spark-aggregated (price, count) pairs, not from original CSV."""
    if not prices:
        return []
    max_price = max(Decimal(str(price)) for price, _ in prices)
    step = Decimal('50') * max(1, int(max_price / Decimal('1000')) + (1 if max_price % 1000 else 0))
    # Last bin includes all remaining prices and has no upper bound.
    full = int(max_price // step)
    result = []
    for index in range(full + 1):
        lower = step * index
        upper = step * (index + 1) if index < full else None
        count = sum(int(n) for p, n in prices if Decimal(str(p)) >= lower and (upper is None or Decimal(str(p)) < upper))
        result.append({'lower': decimal_2(lower), 'upper': decimal_2(upper) if upper is not None else None, 'count': count})
    assert sum(x['count'] for x in result) == sum(int(n) for _, n in prices)
    return result


def main():
    arg = argparse.ArgumentParser()
    for param in ('batch-id', 'input-uri', 'dictionaries-uri', 'output-uri'):
        arg.add_argument('--' + param, required=True)
    args = arg.parse_args()

    from pyspark.sql import SparkSession, functions as F, types as T

    spark = SparkSession.builder.appName('tourism-spark-sql-' + args.batch_id).getOrCreate()
    try:
        raw_columns = [T.StructField(col, T.DecimalType(12, 2) if col in ('price_min', 'price_max') else T.StringType(), True) for col in COLUMNS]
        schema = T.StructType(raw_columns)
        df = (spark.read.schema(schema).option('header', 'true')
              .option('enforceSchema', 'false').option('mode', 'FAILFAST')
              .option('multiLine', 'false').option('quote', '"').option('escape', '"')
              .csv(args.input_uri))
        df = df.withColumn('types_array', F.from_json(F.col('type_codes'), T.ArrayType(T.StringType())))
        df.persist()
        total = df.count()
        if total == 0:
            raise ValueError('Empty Spark input')
        if df.filter(F.col('batch_id') != args.batch_id).limit(1).count():
            raise ValueError('Mixed batch ID in Spark input')
        if df.filter(F.col('types_array').isNull()).limit(1).count():
            raise ValueError('Unparseable type_codes JSON')
        df.createOrReplaceTempView('attractions')
        types = df.select('country_code', F.explode_outer('types_array').alias('type_code'))
        types.createOrReplaceTempView('attraction_types')
        batch, engine = args.batch_id, 'spark_sql'
        records = []
        # All required count scopes must be calculated through Spark SQL, not local CSV parsing.
        queries = {
            'all': 'SELECT count(*) AS count FROM attractions',
            'province': 'SELECT country_code, province_key, count(*) AS count FROM attractions GROUP BY country_code, province_key',
            'city': 'SELECT country_code, city_key, count(*) AS count FROM attractions GROUP BY country_code, city_key',
            'grade': 'SELECT country_code, grade_system, grade_status, grade_level, count(*) AS count FROM attractions GROUP BY country_code, grade_system, grade_status, grade_level',
            'city_grade': 'SELECT country_code, city_key, grade_system, grade_status, grade_level, count(*) AS count FROM attractions GROUP BY country_code, city_key, grade_system, grade_status, grade_level',
            'type': 'SELECT country_code, type_code, count(*) AS count FROM attraction_types GROUP BY country_code, type_code',
        }
        count_groups = {}
        for scope, sql in queries.items():
            rows = [row.asDict() for row in spark.sql(sql).collect()]
            count_groups[scope] = rows
            for row in rows:
                dims = count_dimensions(scope, row)
                records.append(record(batch, engine, 'attraction_count', dims, 'ok', {'count': int(row['count'])}))
        for scope in ('all', 'province', 'city', 'grade', 'city_grade'):
            if sum(x['count'] for x in count_groups[scope]) != total:
                raise ValueError('Spark total count mismatch for ' + scope)
        quality = spark.sql('''SELECT count(*) AS standard_count,
          sum(CASE WHEN city_key IS NULL THEN 1 ELSE 0 END) AS missing_city_count,
          sum(CASE WHEN grade_status = 'unknown' THEN 1 ELSE 0 END) AS unknown_grade_count,
          sum(CASE WHEN grade_status = 'conflict' THEN 1 ELSE 0 END) AS conflicting_grade_count,
          sum(CASE WHEN size(types_array) = 0 THEN 1 ELSE 0 END) AS missing_type_count,
          sum(CASE WHEN price_form = 'unknown' THEN 1 ELSE 0 END) AS unknown_price_count,
          sum(CASE WHEN price_form = 'conflict' THEN 1 ELSE 0 END) AS conflicting_price_count
          FROM attractions''').first().asDict()
        records.append(record(batch, engine, 'data_quality', {'scope': 'all'}, 'ok', {k: int(v) for k, v in quality.items()}))

        # Policies are read from the same HDFS metadata namespace, never from test defaults.
        policies_text = ''.join(x.value for x in spark.read.text(args.dictionaries_uri).collect())
        dictionary = json.loads(policies_text)
        policies = dictionary.get('price_policies')
        if not isinstance(policies, list):
            raise ValueError('Invalid dictionaries price_policies')
        policy_ids = set()
        for policy in policies:
            if (not isinstance(policy, dict) or not policy.get('id') or not policy.get('currency')
                    or not policy.get('approval_ref') or policy['id'] in policy_ids):
                raise ValueError('Incomplete/duplicate price policy in dictionary')
            policy_ids.add(policy['id'])
        if not policies:
            dims = {'scope': 'all', 'currency': None, 'price_policy_id': None}
            for metric in ('price_summary', 'price_histogram'):
                records.append(record(batch, engine, metric, dims, 'pending_policy', None))
        else:
            policy_df = spark.createDataFrame([(p['id'], p['currency']) for p in policies], ['price_policy_id', 'currency'])
            submitted = df.filter(F.col('price_policy_id').isNotNull())
            valid = (submitted.join(F.broadcast(policy_df), ['price_policy_id', 'currency'], 'inner')
                     .filter(F.col('price_form').isin('exact', 'free'))
                     .filter(F.col('price_min').isNotNull() & F.col('price_max').isNotNull())
                     .filter((F.col('price_min') == F.col('price_max')) & (F.col('price_min') >= F.lit(0))))
            if submitted.count() != valid.count():
                raise ValueError('Price policy tagged data is not fully eligible; reject ambiguous records')
            for scope in ('all', 'city', 'grade'):
                keys = [k for k in COUNT_DIMENSIONS[scope] if k != 'scope']
                price_keys = keys + ['price_policy_id', 'currency']
                aggregates = (valid.groupBy(*price_keys)
                              .agg(F.count('*').alias('valid_count'), F.min('price_min').alias('minimum'),
                                   F.max('price_min').alias('maximum'), F.sum('price_min').alias('total_price')))
                summary_map = {}
                for r in aggregates.collect():
                    d = r.asDict()
                    summary_map[tuple(d.get(k) for k in price_keys)] = d
                price_counts = valid.groupBy(*(price_keys + ['price_min'])).count()
                price_map = {}
                for r in price_counts.collect():
                    d = r.asDict()
                    k = tuple(d.get(x) for x in price_keys)
                    price_map.setdefault(k, []).append((d['price_min'], d['count']))
                for group in count_groups[scope]:
                    for policy in policies:
                        p_id, currency = policy['id'], policy['currency']
                        key = tuple(group.get(k) for k in keys) + (p_id, currency)
                        summary = summary_map.get(key)
                        n, candidates = int(summary['valid_count']) if summary else 0, int(group['count'])
                        dims = dict(count_dimensions(scope, group), price_policy_id=p_id, currency=currency)
                        value = {'candidate_count': candidates, 'valid_count': n,
                                 'coverage': price_coverage(n, candidates),
                                 'min': decimal_2(summary['minimum']) if n else None,
                                 'max': decimal_2(summary['maximum']) if n else None,
                                 'mean': decimal_2(Decimal(summary['total_price']) / n) if n else None}
                        records.append(record(batch, engine, 'price_summary', dims, 'ok' if n else 'no_data', value))
                        bins = histogram(price_map.get(key, []))
                        if sum(item['count'] for item in bins) != n:
                            raise ValueError('Histogram counts inconsistent with Spark price summary')
                        records.append(record(batch, engine, 'price_histogram', dims, 'ok' if n else 'no_data',
                                              {'valid_count': n, 'bins': bins}))
        # Spark output remains an HDFS job artifact; the driver only serializes Spark aggregates.
        spark.sparkContext.parallelize([json_line(r) for r in records], 1).saveAsTextFile(args.output_uri)
        print('TOURISM_SPARK_STATISTICS_COMPLETE count_records=' + str(len(records)))
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
