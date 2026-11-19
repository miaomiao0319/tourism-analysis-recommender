"""Contract-focused constructed tests, NOT real Spark/YARN/HDFS execution."""
import csv
import hashlib
import io
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from analysis.common import (COLUMNS, canonical_json, count_dimensions, output_files,
                             parse_jsonl, record, source_context, valid_id, validate_csv_bytes)
from analysis.mapreduce.mapper import transform_line
from analysis.mapreduce.reducer import aggregate
from analysis.mapreduce.converter import convert_output
from analysis.runner import require_runtime_versions, verified_stat_rows
from analysis.spark.job import decimal_2, histogram, price_coverage


def sample(**kw):
    row = {c: '' for c in COLUMNS}
    row.update(batch_id='test_1', attraction_id='A1', name='景点, “一号”', country_code='CN',
               province_key='p1', province_name='甲省', city_key='', city_name='',
               grade_system='UNKNOWN', grade_status='unknown', grade_level='',
               type_codes='["nature","museum"]', price_form='unknown',
               source_refs='{"name":["src1"]}', collected_at='2026-10-15T00:00:00Z')
    row.update(kw)
    return row


def csv_blob(rows):
    f = io.StringIO(newline='')
    writer = csv.writer(f, lineterminator='\n')
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([row[col] for col in COLUMNS])
    return f.getvalue().encode('utf-8')


class AnalysisContractTests(unittest.TestCase):
    def test_csv_preflight_handles_quoted_comma_and_json(self):
        validate_csv_bytes(csv_blob([sample()]), 'test_1', 1)

    def test_preflight_rejects_wrong_header(self):
        with self.assertRaises(ValueError):
            validate_csv_bytes(csv_blob([sample()]).replace(b'country_code', b'country_xxxx'), 'test_1', 1)

    def test_preflight_rejects_duplicate_id(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_csv_bytes(csv_blob([sample(), sample()]), 'test_1', 2)

    def test_preflight_rejects_mixed_batch(self):
        with self.assertRaisesRegex(ValueError, 'wrong batch'):
            validate_csv_bytes(csv_blob([sample(batch_id='wrong')]), 'test_1', 1)

    def test_preflight_rejects_unphysical_multiline_record(self):
        with self.assertRaisesRegex(ValueError, 'line breaks'):
            validate_csv_bytes(csv_blob([sample(name='line\nbreak')]), 'test_1', 1)

    def test_id_validation_protects_paths(self):
        for item in ('../hi', 'abc/def', '', '中', 'a'*65):
            with self.subTest(item=item), self.assertRaises(ValueError):
                valid_id(item)

    def test_mapper_and_reducer_preserve_unknown_and_conflict(self):
        rows = [sample(), sample(attraction_id='A2', country_code='US', city_key='US:c2',
                  grade_status='conflict'), sample(attraction_id='A3', country_code='CN',
                  city_key='CN:c1', grade_system='CN_A', grade_status='rated', grade_level='5A')]
        blob = csv_blob(rows).decode('utf-8')
        mapped = [out for line in blob.splitlines() for out in transform_line(line, 'test_1')]
        self.assertEqual(len(mapped), 6)
        reduced = '\n'.join(aggregate(sorted(x + '\n' for x in mapped)))
        results = convert_output(reduced, 'test_1')
        self.assertEqual(sum(x['value']['count'] for x in results if x['dimensions']['scope']=='city'), 3)
        self.assertEqual(sum(x['value']['count'] for x in results if x['dimensions']['scope']=='grade'), 3)
        self.assertTrue(any(x['dimensions'].get('city_key') is None for x in results))
        self.assertTrue(any(x['dimensions'].get('grade_status') == 'conflict' for x in results))
        verified_stat_rows(results, batch='test_1', engine='mapreduce', count=3, policies=[])

    def test_mapper_rejects_wrong_batch_and_row_length(self):
        for line in ('abc,def', csv_blob([sample(batch_id='other')]).decode().splitlines()[1]):
            with self.assertRaises(ValueError):
                transform_line(line, 'test_1')

    def test_reducer_rejects_truncated_key(self):
        with self.assertRaises(ValueError):
            list(aggregate(['bad\t1\n']))

    def test_duplicate_statistics_rejected(self):
        item = record('test_1', 'mapreduce', 'attraction_count',
                      {'scope':'city','country_code':'CN','city_key':None}, 'ok', {'count':1})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_jsonl(json.dumps(item)+'\n'+json.dumps(item), 'test_1','mapreduce')

    def test_price_decimal_format_and_coverage(self):
        self.assertEqual(decimal_2(Decimal('4.005')), '4.01')
        self.assertEqual(price_coverage(1,3), '0.333333')
        self.assertIsNone(price_coverage(0,0))

    def test_histogram_bounds_and_zero_price(self):
        bins = histogram([(Decimal('0.00'),2), (Decimal('49.99'),1),
                          (Decimal('50.00'),3), (Decimal('100.00'),1)])
        self.assertEqual([x['count'] for x in bins], [3,3,1])
        self.assertEqual([x['upper'] for x in bins], ['50.00','100.00',None])

    def test_histogram_empty(self):
        self.assertEqual(histogram([]), [])

    def test_spark_import_requires_no_pyspark_until_submitted(self):
        from analysis.spark.job import price_coverage as func
        self.assertEqual(func(1,2), '0.500000')

    def test_pending_policy_validation(self):
        base = [record('test_1','spark_sql','attraction_count',count_dimensions(s,{}),'ok',{'count':1})
                for s in ('all','province','city','grade','city_grade','type')]
        base.append(record('test_1','spark_sql','data_quality', {'scope':'all'},'ok', {'standard_count':1}))
        dims = {'scope':'all', 'currency':None, 'price_policy_id':None}
        for metric in ('price_summary','price_histogram'):
            base.append(record('test_1','spark_sql',metric,dims,'pending_policy',None))
        verified_stat_rows(base, batch='test_1', engine='spark_sql', count=1, policies=[])
        with self.assertRaises(ValueError):
            verified_stat_rows(base[:-1],batch='test_1',engine='spark_sql',count=1,policies=[])

    def test_source_context_validates_hdfs_bytes(self):
        data = csv_blob([sample()])
        dictionary = b'{"price_policies": []}'
        digest = lambda x: hashlib.sha256(x).hexdigest()
        manifest = {'batch_id':'test_1','contract_version':'1.0','data_kind':'test','standard_count':1,
                    'standard_sha256':digest(data),'dictionaries_sha256':digest(dictionary)}
        content = {'attractions.csv':data,'dictionaries.json':dictionary,'manifest.json':json.dumps(manifest).encode()}
        with patch('analysis.common.hdfs_cat', side_effect=lambda _, path: content[path.rsplit('/',1)[-1]]):
            result = source_context('hdfs','/tourism','test_1','hdfs://localhost:9000')
        self.assertEqual(result['manifest']['standard_count'],1)

    def test_source_context_rejects_mismatched_sha(self):
        data = csv_blob([sample()])
        dictionary = b'{"price_policies": []}'
        manifest = {'batch_id':'test_1','contract_version':'1.0','data_kind':'test','standard_count':1,
                    'standard_sha256':'a'*64,'dictionaries_sha256':hashlib.sha256(dictionary).hexdigest()}
        content = {'attractions.csv':data,'dictionaries.json':dictionary,'manifest.json':json.dumps(manifest).encode()}
        with patch('analysis.common.hdfs_cat', side_effect=lambda _, path: content[path.rsplit('/',1)[-1]]):
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
                source_context('hdfs','/tourism','test_1','hdfs://localhost:9000')

    def test_runtime_version_preflight_rejects_non_baseline_tools(self):
        good_java = subprocess.CompletedProcess([], 0, 'openjdk version "11.0.32"\n')
        bad_hadoop = subprocess.CompletedProcess([], 0, 'Hadoop 3.4.1\n')
        with patch('analysis.runner.subprocess.run', side_effect=[good_java, bad_hadoop]):
            with self.assertRaisesRegex(RuntimeError, 'Hadoop 3.4.3'):
                require_runtime_versions(engine='mapreduce', java='/jdk/bin/java',
                                         hadoop='/hadoop/bin/hadoop', python='/venv/bin/python', env={})

    def test_runtime_version_preflight_accepts_required_spark_versions(self):
        results = [
            subprocess.CompletedProcess([], 0, 'openjdk version "11.0.32"\n'),
            subprocess.CompletedProcess([], 0, 'Hadoop 3.4.3\n'),
            subprocess.CompletedProcess([], 0, '3.5.8\n'),
        ]
        with patch('analysis.runner.subprocess.run', side_effect=results):
            require_runtime_versions(engine='spark_sql', java='/jdk/bin/java',
                                     hadoop='/hadoop/bin/hadoop', python='/venv/bin/python', env={})


if __name__ == '__main__':
    unittest.main()

class StreamingSubprocessTests(unittest.TestCase):
    def test_standalone_streaming_protocol_smoke(self):
        # This checks command-line stdin/stdout plumbing; it is NOT YARN execution.
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        csv_input = csv_blob([sample(), sample(attraction_id='A2', grade_status='conflict')]).decode('utf-8')
        mapper = subprocess.run([sys.executable, str(root / 'analysis/mapreduce/mapper.py'), '--batch-id', 'test_1'],
                                input=csv_input, capture_output=True, text=True, check=True)
        reducer = subprocess.run([sys.executable, str(root / 'analysis/mapreduce/reducer.py')],
                                 input='\n'.join(sorted(mapper.stdout.splitlines()))+'\n',
                                 capture_output=True, text=True, check=True)
        rows = convert_output(reducer.stdout, 'test_1')
        verified_stat_rows(rows, batch='test_1', engine='mapreduce', count=2, policies=[])
