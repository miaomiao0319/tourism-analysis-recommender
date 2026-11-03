import copy
import unittest
from database.statistics_check import dimension_key, reconcile_counts, validate_run_identity


def sample(engine):
    return [dict(batch_id='test', engine=engine, metric='attraction_count', dimensions={'scope':'city','country_code':'CN','city_key':None}, status='ok', value={'count':1}),
            dict(batch_id='test', engine=engine, metric='attraction_count', dimensions={'scope':'grade','country_code':'CN','grade_system':'UNKNOWN','grade_status':'unknown','grade_level':None}, status='ok', value={'count':1})]


class StatisticsCheckTests(unittest.TestCase):
    def test_runs_must_reference_same_snapshot_and_engine(self):
        manifest = dict(batch_id='test', contract_version='1.0', standard_sha256='a'*64)
        left = dict(batch_id='test', engine='mapreduce', contract_version='1.0', input_sha256='a'*64)
        right = dict(batch_id='test', engine='spark_sql', contract_version='1.0', input_sha256='a'*64)
        self.assertFalse(validate_run_identity(manifest, left, right)['full_run_audit'])
        for field, value in (('input_sha256', 'b'*64), ('batch_id','other'), ('engine','mapreduce'), ('contract_version','2.0')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run_identity(manifest, left, dict(right, **{field:value}))
    def test_matching_counts_are_not_full_release(self):
        result = reconcile_counts(sample('mapreduce'), sample('spark_sql'), 'test', 1)
        self.assertEqual(result['count_reconciliation'], 'passed')
        self.assertFalse(result['ready_for_import'])

    def test_disagreement_duplicates_and_missing_groups_fail(self):
        original = sample('spark_sql')
        for mutated in (original[:1], original + [copy.deepcopy(original[0])],
                        [dict(original[0], value={'count':2}), original[1]],
                        [dict(original[0], value={'count':True}), original[1]]):
            with self.subTest(mutated=mutated), self.assertRaises(ValueError):
                reconcile_counts(sample('mapreduce'), mutated, 'test', 1)

    def test_dimension_key_is_order_independent_and_type_checked(self):
        self.assertEqual(dimension_key({'a':'中','b':None}), dimension_key({'b':None,'a':'中'}))
        with self.assertRaises(ValueError):
            dimension_key({'a':1})
