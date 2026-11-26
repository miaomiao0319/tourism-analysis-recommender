import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cleaning.qianling_city import HASHES, RAW, verify_entities


class QianlingCityTests(unittest.TestCase):
    def test_requires_pre_cutoff_entities_and_matching_administrative_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / RAW
            raw.mkdir(parents=True)
            requests = [dict(url='https://example.org/' + q + '.json', sha256=digest)
                        for q, digest in HASHES.items()]
            (raw / 'run.json').write_text(json.dumps({'status': 'success', 'requests': requests}), encoding='utf-8')
            def entity(qid, target, rank, labels, modified='2026-09-01T00:00:00Z'):
                value = {'modified': modified, 'labels': labels,
                         'claims': {'P131': [{'rank': rank, 'mainsnak': {'datavalue': {'value': {'id': target}}}}]}}
                (raw / (qid + '.raw')).write_text(json.dumps({'entities': {qid: value}}), encoding='utf-8')
            entity('Q950653', 'Q1201675', 'normal', {'en': {'value': 'Qianling Mausoleum'}})
            entity('Q1201675', 'Q497341', 'preferred', {'zh': {'value': '乾县'}})
            with patch('cleaning.qianling_city.sha', side_effect=lambda p: HASHES[p.stem]):
                verify_entities(root)
                entity('Q1201675', 'Q497341', 'preferred', {'zh': {'value': '乾县'}}, '2026-11-01T00:00:00Z')
                with self.assertRaisesRegex(ValueError, 'postdates'):
                    verify_entities(root)
                entity('Q1201675', 'Q999', 'preferred', {'zh': {'value': '乾县'}})
                with self.assertRaisesRegex(ValueError, 'chain mismatch'):
                    verify_entities(root)


if __name__ == '__main__':
    unittest.main()
