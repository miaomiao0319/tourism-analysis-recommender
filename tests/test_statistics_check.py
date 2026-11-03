import copy
import unittest
from database.statistics_check import check_data_quality, check_overall_price_summary, dimension_key, reconcile_counts, validate_run_identity


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

    def test_quality_reconciles_overlapping_missing_fields(self):
        rows = [dict(batch_id='test', city_key='', grade_status='unknown', type_codes=[], price_form='unknown'),
                dict(batch_id='test', city_key='CN:1', grade_status='conflict', type_codes=['park'], price_form='conflict')]
        value = dict(standard_count=2, missing_city_count=1, unknown_grade_count=1,
                     conflicting_grade_count=1, missing_type_count=1, unknown_price_count=1,
                     conflicting_price_count=1)
        record = dict(batch_id='test', engine='spark_sql', metric='data_quality',
                      dimensions={'scope': 'all'}, status='ok', value=value)
        self.assertFalse(check_data_quality(rows, [record], 'test')['ready_for_import'])
        variants = [[], [record, record], [dict(record, value=dict(value, missing_city_count=0))],
                    [dict(record, value=dict(value, standard_count=True))],
                    [dict(record, dimensions={'scope': 'city'})], [dict(record, engine='mapreduce')]]
        for records in variants:
            with self.subTest(records=records), self.assertRaises(ValueError):
                check_data_quality(rows, records, 'test')
        with self.assertRaises(ValueError):
            check_data_quality([dict(rows[0], type_codes='[]')], [record], 'test')

    def test_overall_price_summary_checks_eligibility_and_rounding(self):
        base = dict(batch_id='test', currency='CNY', price_policy_id='policy')
        rows = [dict(base, price_form='free', price_min='0.00', price_max='0.00'),
                dict(base, price_form='exact', price_min='0.01', price_max='0.01'),
                dict(base, price_form='from', price_min='1.00', price_max=None)]
        value = dict(candidate_count=3, valid_count=2, coverage='0.666667',
                     min='0.00', max='0.01', mean='0.01')
        record = dict(batch_id='test', engine='spark_sql', metric='price_summary',
                      dimensions={'scope':'all', 'currency':'CNY', 'price_policy_id':'policy'},
                      status='ok', value=value)
        self.assertFalse(check_overall_price_summary(rows, [record], 'test', 'CNY', 'policy')['ready_for_import'])
        variants = [[record, record], [dict(record, value=dict(value, valid_count=3))],
                    [dict(record, value=dict(value, mean='0.00'))],
                    [dict(record, value=dict(value, candidate_count=True))],
                    [dict(record, engine='mapreduce')]]
        for records in variants:
            with self.subTest(records=records), self.assertRaises(ValueError):
                check_overall_price_summary(rows, records, 'test', 'CNY', 'policy')
        with self.assertRaises(ValueError):
            check_overall_price_summary([dict(rows[1], price_max='0.02')], [record], 'test', 'CNY', 'policy')

    def test_overall_price_summary_without_valid_prices(self):
        row = dict(batch_id='test', currency='CNY', price_policy_id=None, price_form='unknown')
        record = dict(batch_id='test', engine='spark_sql', metric='price_summary',
                      dimensions={'scope':'all', 'currency':'CNY', 'price_policy_id':'policy'},
                      status='no_data', value=dict(candidate_count=1, valid_count=0, coverage='0.000000',
                                                   min=None, max=None, mean=None))
        check_overall_price_summary([row], [record], 'test', 'CNY', 'policy')
        with self.assertRaises(ValueError):
            check_overall_price_summary([row], [dict(record, status='ok')], 'test', 'CNY', 'policy')
