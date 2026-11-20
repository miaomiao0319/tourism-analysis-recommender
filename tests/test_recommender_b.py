"""Member B construct-only contract tests. No real dataset/database/HDFS involved."""
import json
import unittest
from copy import deepcopy

from backend.app.services.recommender import (
    RecommendationError, MODE_MATRICES, ahp_weights, recommend, RULE_VERSION,
)

BATCH = 'test_b_001'


def dataset(prices=True):
    return {
        'meta': {'batch_id': BATCH, 'data_kind': 'test', 'contract_version': '1.0'},
        'info': {
            'countries': ['CN'],
            'dictionaries': {
                'regions': [
                    {'key': 'cn:bj', 'name': '北京', 'country_code': 'CN', 'level': 'province', 'parent_key': None},
                    {'key': 'cn:bj:bj', 'name': '北京市', 'country_code': 'CN', 'level': 'city', 'parent_key': 'cn:bj'},
                    {'key': 'cn:gd', 'name': '广东', 'country_code': 'CN', 'level': 'province', 'parent_key': None},
                    {'key': 'cn:gd:gz', 'name': '广州市', 'country_code': 'CN', 'level': 'city', 'parent_key': 'cn:gd'},
                ],
                'types': [{'code': 'nature', 'label': '自然风景'}, {'code': 'culture', 'label': '历史文化'}, {'code': 'family', 'label': '亲子'}],
                'grade_systems': [{'code': 'CN_A', 'levels': ['1A', '2A', '3A', '4A', '5A']}],
                'price_policies': [{'id': 'test_policy', 'currency': 'CNY', 'ticket_basis': '构造票种', 'eligibility_rule': '测试'}] if prices else [],
            },
        },
    }


def attraction(i='1', *, city='cn:bj:bj', province='cn:bj', tags=None, grade='4A',
               price=None, form='exact', policy='test_policy', currency='CNY', evidence=True):
    if tags is None:
        tags = ['nature']
    return {
        'batch_id': BATCH, 'attraction_id': f'a_{i}', 'name': f'构造景点{i}',
        'country_code': 'CN', 'province_key': province,
        'province_name': '北京市' if province == 'cn:bj' else '广东省',
        'city_key': city, 'city_name': '北京市' if city == 'cn:bj:bj' else '广州市',
        'grade_system': 'CN_A' if grade is not None else 'UNKNOWN',
        'grade_status': 'rated' if grade is not None else 'unknown', 'grade_level': grade,
        'type_codes': list(tags),
        'price_form': form if price is not None else 'unknown',
        'price_min': f'{price:.2f}' if price is not None else None,
        'price_max': f'{price:.2f}' if price is not None else None,
        'currency': currency if price is not None else None,
        'price_basis': '构造门票' if price is not None else None,
        'price_policy_id': policy if price is not None else None,
        'price_raw': '构造价格文本' if price is not None else None,
        'source_refs': {'name': ['src_1'], 'location': ['src_1'], 'grade': ['src_1'], 'types': ['src_1'],
                        'price': ['src_1'] if evidence and price is not None else []},
        'collected_at': '2026-10-19T08:00:00Z',
    }


def preferences(**overrides):
    p = {'country_code': 'CN', 'type_codes': ['nature'], 'mode': 'balanced'}
    p.update(overrides)
    return p


class BRecommendationTests(unittest.TestCase):
    def assert_code(self, code, fn):
        with self.assertRaises(RecommendationError) as raised:
            fn()
        self.assertEqual(code, raised.exception.code)

    def test_ahp_mode_weights_and_consistency(self):
        expected = {'balanced': (1/3, 1/3, 1/3), 'interest': (.6, .2, .2),
                    'economy': (.2, .2, .6), 'quality': (.2, .6, .2)}
        for mode, matrix in MODE_MATRICES.items():
            with self.subTest(mode=mode):
                weights, cr = ahp_weights(matrix)
                self.assertAlmostEqual(cr, 0., places=9)
                for x, y in zip(weights, expected[mode]):
                    self.assertAlmostEqual(x, y, places=9)

    def test_bad_ahp_matrix(self):
        self.assert_code('INVALID_PARAMETER', lambda: ahp_weights([[1, 2], [1, 1]]))
        self.assert_code('INVALID_PARAMETER', lambda: ahp_weights([[0]]))
        self.assert_code('INVALID_PARAMETER', lambda: ahp_weights([[float('nan')]]))
        self.assert_code('INVALID_PARAMETER', lambda: ahp_weights([[1, 3, 5], [1/3, 1, 7], [1/5, 1/7, 1]]))

    def test_entire_attraction_and_output_contract(self):
        row = attraction()
        result = recommend([row], preferences(), dataset=dataset())
        self.assertEqual(set(result), {'items', 'candidate_count', 'returned_count', 'limit', 'rule_version', 'preferences', 'empty_reason', 'algorithm_info'})
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(result['returned_count'], 1)
        self.assertEqual(result['rule_version'], RULE_VERSION)
        self.assertEqual(result['items'][0]['attraction'], row)
        self.assertEqual(set(result['items'][0]), {'attraction', 'reasons', 'topsis_score', 'topsis_rank'})
        self.assertTrue(result['items'][0]['reasons'])
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_uses_all_candidates_beyond_list_page(self):
        result = recommend((attraction(str(x)) for x in range(27)), preferences(), limit=10, dataset=dataset())
        self.assertEqual(result['candidate_count'], 27)
        self.assertEqual(result['returned_count'], 10)

    def test_region_country_city_and_province(self):
        rows = [attraction('bj'), attraction('gz', city='cn:gd:gz', province='cn:gd')]
        self.assertEqual(recommend(rows, preferences(city_key='cn:bj:bj'), dataset=dataset())['candidate_count'], 1)
        self.assertEqual(recommend(rows, preferences(province_key='cn:gd'), dataset=dataset())['candidate_count'], 1)
        self.assert_code('INVALID_FILTER', lambda: recommend(rows, preferences(province_key='cn:gd', city_key='cn:bj:bj'), dataset=dataset()))
        self.assert_code('INVALID_FILTER', lambda: recommend(rows, preferences(country_code='US'), dataset=dataset()))
        self.assert_code('INVALID_FILTER', lambda: recommend(rows, preferences(city_key='invalid'), dataset=dataset()))

    def test_interests_all_match_without_penalizing_extra_tags(self):
        rows = [attraction('n', tags=['nature']), attraction('nc', tags=['nature','culture','family']), attraction('c', tags=['culture'])]
        result = recommend(rows, preferences(type_codes=['nature', 'culture']), dataset=dataset())
        self.assertEqual(result['candidate_count'], 3)
        self.assertEqual(result['items'][0]['attraction']['attraction_id'], 'a_nc')
        self.assertEqual(result['algorithm_info']['available_weights']['interest'], 0.5)
        all_user_tags = [attraction('one', tags=['nature','culture']), attraction('extra', tags=['nature','culture','family'])]
        same = recommend(all_user_tags, preferences(type_codes=['nature','culture']), dataset=dataset())
        self.assertEqual(same['items'][0]['topsis_score'], same['items'][1]['topsis_score'])

    def test_empty_interests_drops_interest_weight(self):
        result = recommend([attraction('1', grade='5A'), attraction('2', grade='3A')], preferences(type_codes=[]), dataset=dataset())
        self.assertEqual(set(result['algorithm_info']['available_weights']), {'grade'})
        self.assertEqual(result['items'][0]['attraction']['grade_level'], '5A')

    def test_no_budget_does_not_claim_free_or_price_matching(self):
        row = attraction('u', price=None)
        result = recommend([row], preferences(), dataset=dataset(prices=False))
        self.assertEqual(result['candidate_count'], 1)
        self.assertNotIn('price', result['algorithm_info']['available_weights'])
        self.assertFalse(any('免费' in s or '预算' in s for s in result['items'][0]['reasons']))

    def test_budget_policy_not_ready_and_unknown_policy(self):
        budget = {'amount': '80.00', 'currency': 'CNY', 'price_policy_id': 'test_policy'}
        self.assert_code('PRICE_POLICY_NOT_READY', lambda: recommend([], preferences(budget=budget), dataset=dataset(prices=False)))
        self.assert_code('INVALID_FILTER', lambda: recommend([], preferences(budget=dict(budget, price_policy_id='not_known')), dataset=dataset()))
        self.assert_code('INVALID_FILTER', lambda: recommend([], preferences(budget=dict(budget, currency='USD')), dataset=dataset()))

    def test_budget_boundary_7999_8000_and_free_zero(self):
        candidates = [attraction('cheap', price=79.99), attraction('exact', price=80), attraction('high', price=80.01),
                      attraction('free', price=0, form='free'), attraction('unknown')]
        budget = {'amount': '80.00', 'currency': 'CNY', 'price_policy_id': 'test_policy'}
        result = recommend(candidates, preferences(budget=budget), dataset=dataset())
        self.assertEqual(result['candidate_count'], 3)
        self.assertEqual(result['preferences']['budget']['amount'], '80.00')
        zero = recommend(candidates, preferences(budget=dict(budget, amount='0.00')), dataset=dataset())
        self.assertEqual(zero['candidate_count'], 1)
        self.assertEqual(zero['items'][0]['attraction']['attraction_id'], 'a_free')
        self.assertTrue(any('免费' in s for s in zero['items'][0]['reasons']))
        threshold = recommend(candidates, preferences(budget=dict(budget, amount='79.99')), dataset=dataset())
        self.assertEqual(threshold['candidate_count'], 2)

    def test_no_fake_prices_or_cross_currency_or_policy(self):
        rows = [attraction('range', price=30, form='range'), attraction('from', price=30, form='from'),
                attraction('wrong', price=30, policy='other'), attraction('usd', price=30, currency='USD'),
                attraction('noevidence', price=30, evidence=False), attraction('exact', price=30)]
        budget = {'amount':'80.00','currency':'CNY','price_policy_id':'test_policy'}
        result = recommend(rows, preferences(budget=budget), dataset=dataset())
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(result['items'][0]['attraction']['attraction_id'], 'a_exact')

    def test_budget_invalid_formats(self):
        for raw in [0, -1, 'NaN', '80.001', '1e2', ' 80', '+80', '10000000000', True, '']:
            with self.subTest(raw=raw):
                b = {'amount':raw,'currency':'CNY','price_policy_id':'test_policy'}
                self.assert_code('INVALID_PARAMETER', lambda: recommend([], preferences(budget=b), dataset=dataset()))
        self.assert_code('INVALID_PARAMETER', lambda: recommend([], preferences(budget={'amount':'80.00'}), dataset=dataset()))

    def test_empty_filters_and_no_matching_result(self):
        self.assert_code('EMPTY_PREFERENCES', lambda: recommend([], {'mode':'quality'}, dataset=dataset()))
        result = recommend([], preferences(), limit=50, dataset=dataset())
        self.assertEqual(result['items'], [])
        self.assertEqual(result['empty_reason'], 'NO_MATCHING_CANDIDATES')
        self.assertEqual(result['returned_count'], 0)
        self.assertEqual(result['candidate_count'], 0)

    def test_unknown_grade_kept_without_fictitious_grade(self):
        row = attraction('u', grade=None)
        result = recommend([row], preferences(mode='quality'), dataset=dataset())
        self.assertEqual(result['candidate_count'], 1)
        self.assertFalse(any('等级：' in s for s in result['items'][0]['reasons']))

    def test_four_modes_change_rank_when_objectives_conflict(self):
        budget = {'amount':'100.00','currency':'CNY','price_policy_id':'test_policy'}
        rows = [attraction('grade', grade='5A', price=100), attraction('cheap', grade='1A', price=10)]
        economy = recommend(rows, preferences(mode='economy', budget=budget), dataset=dataset())
        quality = recommend(rows, preferences(mode='quality', budget=budget), dataset=dataset())
        self.assertEqual(economy['items'][0]['attraction']['attraction_id'], 'a_cheap')
        self.assertEqual(quality['items'][0]['attraction']['attraction_id'], 'a_grade')

    def test_mmr_changes_ranking_to_add_diversity(self):
        # All eligible by 'nature'; MMR can favor dissimilar tags for later picks.
        rows = [attraction('a', tags=['nature','culture'], grade='5A'),
                attraction('b', tags=['nature','culture'], grade='5A'),
                attraction('c', tags=['nature','family'], grade='5A')]
        result = recommend(rows, preferences(), limit=3, dataset=dataset())
        self.assertEqual(result['items'][0]['attraction']['attraction_id'], 'a_a')
        self.assertEqual(result['items'][1]['attraction']['attraction_id'], 'a_c')
        self.assertEqual(result['items'][1]['topsis_rank'], 3)

    def test_no_mutation_stable_and_one_candidate(self):
        rows = [attraction('2'), attraction('1')]
        before = deepcopy(rows)
        one = recommend(rows[:1], preferences(), dataset=dataset())
        self.assertEqual(one['items'][0]['topsis_score'], 1.0)
        a = recommend(rows, preferences(), dataset=dataset())
        b = recommend(reversed(rows), preferences(), dataset=dataset())
        self.assertEqual(a, b)
        self.assertEqual(rows, before)

    def test_invalid_limit_and_mode(self):
        for limit in (0, 51, -1, True, 2.0):
            self.assert_code('INVALID_PARAMETER', lambda: recommend([], preferences(), limit=limit, dataset=dataset()))
        self.assert_code('INVALID_PARAMETER', lambda: recommend([], preferences(mode='random'), dataset=dataset()))
        self.assert_code('INVALID_PARAMETER', lambda: recommend([], preferences(unknown='x'), dataset=dataset()))

    def test_missing_or_cross_batch_candidates_are_dataset_invalid(self):
        row = attraction()
        self.assert_code('DATASET_INVALID', lambda: recommend([dict(row, batch_id='wrong')], preferences(), dataset=dataset()))
        self.assert_code('DATASET_INVALID', lambda: recommend([row, row], preferences(), dataset=dataset()))
        bad = dict(row)
        del bad['source_refs']
        self.assert_code('DATASET_INVALID', lambda: recommend([bad], preferences(), dataset=dataset()))
        self.assert_code('DATASET_NOT_READY', lambda: recommend([], preferences(), dataset=None))

    def test_input_iteration_errors_not_hidden(self):
        def generator():
            yield attraction('a')
            raise RuntimeError('data stream failed')
        with self.assertRaisesRegex(RuntimeError, 'stream failed'):
            recommend(generator(), preferences(), dataset=dataset())

    def test_labels_and_safety(self):
        row = attraction('x', tags=['nature', 'family'], grade='5A')
        result = recommend([row], preferences(type_codes=['nature']), dataset=dataset())
        self.assertTrue(any('自然风景' in s for s in result['items'][0]['reasons']))
        self.assertEqual(result['algorithm_info']['mmr_lambda'], 0.8)
        self.assertTrue(0 <= result['items'][0]['topsis_score'] <= 1)
        self.assertIn('相对', result['algorithm_info']['score_note'])
        self.assertEqual(result['preferences']['mode'], 'balanced')


if __name__ == '__main__':
    unittest.main()
