"""Convert *actual* reducer output to the shared statistics contract."""
import json
from analysis.common import count_dimensions, json_line, record


def convert_output(raw: str, batch_id: str):
    records = []
    seen = set()
    for text in raw.splitlines():
        key, sep, number = text.partition('\t')
        if not sep or not number.isdecimal():
            raise ValueError('Invalid native MapReduce output')
        dims = json.loads(key)
        scope = dims.get('scope')
        if scope not in ('city', 'grade') or dims != count_dimensions(scope, dims):
            raise ValueError('Invalid reducer dimensions')
        if key in seen:
            raise ValueError('Duplicate reducer dimension')
        seen.add(key)
        records.append(record(batch_id, 'mapreduce', 'attraction_count', dims, 'ok', {'count': int(number)}))
    if not records:
        raise ValueError('Empty MapReduce output')
    return records
