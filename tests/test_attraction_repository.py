import unittest
from decimal import Decimal
from backend.app.repositories.attractions import AttractionRepository, predicates, validate_dimensions


class RepositoryTests(unittest.TestCase):
    def test_invalid_syntax_is_rejected_before_database_connection(self):
        def no_connection():
            raise AssertionError('database must not be contacted')
        repo = AttractionRepository(no_connection)
        for filters in ({'max_price': '-1'}, {'city_key': ''}, {'country_code':'cn'}, {'unknown':'x'}):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValueError, 'INVALID_PARAMETER'):
                repo.list_attractions('batch', filters)
        with self.assertRaisesRegex(ValueError, 'INVALID_PARAMETER'):
            repo.get_attraction('../bad', 'name')

    def test_cross_province_and_grade_mismatches(self):
        dictionary = {'regions': [dict(key='p1', level='province', country_code='CN'), dict(key='p2', level='province', country_code='CN'), dict(key='c1', level='city', country_code='CN', parent_key='p1')], 'types': [], 'grade_systems': [dict(code='CN_A', levels=['4A','5A'])]}
        class Cursor:
            def execute(self, sql, args): pass
            def fetchone(self): return ('CN',)
        cursor = Cursor()
        for filters in ({'province_key':'p2','city_key':'c1'}, {'country_code':'US','city_key':'c1'}, {'grade_system':'UNKNOWN','grade_level':'5A'}, {'grade_system':'CN_A','grade_status':'conflict'}):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValueError, 'INVALID_FILTER'):
                validate_dimensions(cursor, 'batch', filters, dictionary)
        self.assertEqual(validate_dimensions(cursor, 'batch', {'grade_system':'CN_A','grade_level':'5A'}, dictionary)['grade_status'], 'rated')

    def test_search_escape_and_budget_decimal(self):
        where, args, order = predicates('test', {'q': 'a%_!b', 'max_price': '70.00', 'currency': 'CNY', 'price_policy_id': 'p'}, 'name_asc', [{'id':'p','currency':'CNY'}])
        self.assertIn("ESCAPE '!'", where)
        self.assertIn('%a!%!_!!b%', args)
        self.assertEqual(args[-1], Decimal('70.00'))
        self.assertEqual(order, 'name ASC, attraction_id ASC')
        for amount in ('NaN', '1.001', '-1', 70.0):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                predicates('test', {'max_price': amount, 'currency':'CNY', 'price_policy_id':'p'}, 'name_asc', [{'id':'p','currency':'CNY'}])

    def test_unpublished_batch_cannot_be_queried(self):
        class Cursor:
            def execute(self, sql, args): self.sql = sql
            def fetchone(self): return ('loading', '1.0', '{}')
        with self.assertRaisesRegex(ValueError, 'DATASET_NOT_READY'):
            AttractionRepository._ready(Cursor(), 'real_batch')

    def test_price_context_requires_registered_policy_and_currency(self):
        with self.assertRaisesRegex(ValueError, 'PRICE_POLICY_NOT_READY'):
            predicates('test', {'max_price':'0', 'currency':'CNY', 'price_policy_id':'p'}, 'name_asc', [])
        with self.assertRaisesRegex(ValueError, 'INVALID_FILTER'):
            predicates('test', {'max_price':'70', 'currency':'USD', 'price_policy_id':'p'}, 'name_asc', [{'id':'p','currency':'CNY'}])
