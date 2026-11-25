import tempfile
import unittest
from pathlib import Path
from scripts.hadoop_guard import check, datanode_uri


class HadoopGuardTests(unittest.TestCase):
    def test_datanode_chinese_path_is_not_percent_encoded(self):
        path = Path.cwd() / '大三上资料' / 'hadoop' / 'data'
        expected = 'file://' + str(path)
        self.assertEqual(datanode_uri(path), expected)
        self.assertEqual(datanode_uri(path, path.as_uri()), expected)
        self.assertEqual(datanode_uri(path, expected), expected)
        with self.assertRaises(ValueError):
            datanode_uri(path, 'file:///elsewhere/data')

    def test_existing_runtime_is_never_formatted(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / '.runtime' / 'hadoop'
            runtime.mkdir(parents=True)
            (runtime / 'VERSION').write_text('existing')
            with self.assertRaises(FileExistsError):
                check(tmp, '/nonexistent-java', '/nonexistent-hadoop')
            self.assertEqual((runtime / 'VERSION').read_text(), 'existing')

    def test_symlink_cannot_escape_runtime(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            directory = Path(tmp) / '.runtime'
            directory.mkdir()
            try:
                (directory / 'hadoop').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaises(ValueError):
                check(tmp, '/nonexistent-java', '/nonexistent-hadoop')
