import json
import unittest
from unittest.mock import patch

from database.import_statistics import import_records


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if 'FROM dataset_batches' in sql:
            self.result = [('1.0', 'a' * 64, '{}', '{}', '[]', 'loading')]
        elif 'FROM attractions' in sql or 'FROM source_records' in sql:
            self.result = []
        elif 'FROM analysis_results' in sql:
            self.result = list(self.connection.rows)

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result

    def executemany(self, sql, values):
        self.connection.rows.extend(tuple(row[1:]) for row in values)
        if self.connection.fail:
            raise RuntimeError('injected failure')


class Connection:
    def __init__(self):
        self.rows = []
        self.saved = []
        self.fail = False

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.saved = list(self.rows)

    def rollback(self):
        self.rows = list(self.saved)


class ImportStatisticsTests(unittest.TestCase):
    @patch('database.import_statistics.equal_evidence', return_value=True)
    @patch('database.import_statistics.equal_attractions', return_value=True)
    @patch('database.import_statistics.json_lines', return_value=[])
    def test_rollback_repeated_and_changed_input(self, *_):
        connection = Connection()
        manifest = {'contract_version': '1.0', 'standard_sha256': 'a' * 64}
        # The batch row stores the same manifest used by the importer.
        original_execute = Cursor.execute
        def execute(cursor, sql, params=None):
            original_execute(cursor, sql, params)
            if 'FROM dataset_batches' in sql:
                cursor.result = [('1.0', 'a' * 64, json.dumps(manifest), '{}', '[]', 'loading')]
        records = {'mapreduce': [], 'spark_sql': [
            {'engine': 'spark_sql', 'metric': 'attraction_count',
             'dimensions': {'scope': 'all'}, 'status': 'ok', 'value': {'count': 1}}
        ]}
        with patch.object(Cursor, 'execute', execute):
            connection.fail = True
            with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                import_records(connection, 'test', manifest, {}, [], records)
            self.assertEqual(connection.rows, [])
            connection.fail = False
            self.assertFalse(import_records(connection, 'test', manifest, {}, [], records)['repeated'])
            self.assertTrue(import_records(connection, 'test', manifest, {}, [], records)['repeated'])
            records['spark_sql'][0]['value'] = {'count': 2}
            with self.assertRaisesRegex(ValueError, 'Existing statistics differ'):
                import_records(connection, 'test', manifest, {}, [], records)
            self.assertEqual(len(connection.rows), 1)


if __name__ == '__main__':
    unittest.main()
