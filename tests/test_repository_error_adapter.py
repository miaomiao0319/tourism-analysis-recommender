import unittest
from backend.app.repositories.error_adapter import RepositoryAdapter


class FakeAppError(Exception):
    def __init__(self, code, message, details):
        self.code, self.message, self.details = code, message, details


class DatabaseFailure(Exception):
    pass


class RepositoryErrorAdapterTests(unittest.TestCase):
    def test_database_details_are_not_exposed(self):
        class Repository:
            def list_attractions(self, *args):
                raise DatabaseFailure('secret database path and SQL')
        adapter = RepositoryAdapter(Repository(), FakeAppError, (DatabaseFailure,))
        with self.assertRaises(FakeAppError) as raised:
            adapter.list_attractions('batch', {})
        self.assertEqual(raised.exception.code, 'DEPENDENCY_UNAVAILABLE')
        self.assertNotIn('secret', raised.exception.message)
        self.assertEqual(raised.exception.details, {})

    def test_errors_during_iteration_are_mapped(self):
        class Repository:
            def iter_recommendation_candidates(self, *args):
                yield 'first'
                raise DatabaseFailure('private')
        adapter = RepositoryAdapter(Repository(), FakeAppError, (DatabaseFailure,))
        candidates = adapter.iter_recommendation_candidates('batch', {})
        self.assertEqual(next(candidates), 'first')
        with self.assertRaises(FakeAppError) as raised:
            next(candidates)
        self.assertEqual(raised.exception.code, 'DEPENDENCY_UNAVAILABLE')

    def test_unknown_programming_error_is_not_hidden(self):
        class Repository:
            def get_attraction(self, *args):
                raise TypeError('unexpected')
        adapter = RepositoryAdapter(Repository(), FakeAppError, (DatabaseFailure,))
        with self.assertRaises(TypeError):
            adapter.get_attraction('batch', 'id')
