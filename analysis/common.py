"""Member B shared contract helpers. No network, Hadoop or Spark side effects at import."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = (
    'batch_id', 'attraction_id', 'name', 'country_code', 'province_key',
    'province_name', 'city_key', 'city_name', 'grade_system', 'grade_status',
    'grade_level', 'type_codes', 'price_form', 'price_min', 'price_max',
    'currency', 'price_basis', 'price_policy_id', 'price_raw', 'source_refs',
    'collected_at',
)
COUNT_DIMENSIONS = {
    'all': ('scope',),
    'province': ('scope', 'country_code', 'province_key'),
    'city': ('scope', 'country_code', 'city_key'),
    'grade': ('scope', 'country_code', 'grade_system', 'grade_status', 'grade_level'),
    'city_grade': ('scope', 'country_code', 'city_key', 'grade_system', 'grade_status', 'grade_level'),
    'type': ('scope', 'country_code', 'type_code'),
}
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
DIGEST_PATTERN = re.compile(r'^[0-9a-f]{64}$')


def valid_id(value: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError('Invalid batch/run id; expected 1-64 ASCII letters, digits, underscore or hyphen')
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def json_line(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def record(batch: str, engine: str, metric: str, dims: dict, status: str, value):
    if engine not in ('mapreduce', 'spark_sql') or status not in ('ok', 'no_data', 'pending_policy'):
        raise ValueError('Invalid engine or status')
    if any(not isinstance(k, str) or (v is not None and not isinstance(v, str)) for k, v in dims.items()):
        raise ValueError('Bad statistics dimensions')
    return dict(batch_id=batch, engine=engine, metric=metric, dimensions=dims, status=status, value=value)


def count_dimensions(scope: str, values: dict) -> dict:
    keys = COUNT_DIMENSIONS[scope]
    return {key: scope if key == 'scope' else values.get(key) for key in keys}


def validate_csv_bytes(raw: bytes, batch_id: str, expected_count: int) -> None:
    """Independent fast preflight on the immutable HDFS bytes (not a Spark/MapReduce result)."""
    valid_id(batch_id)
    if raw.startswith(b'\xef\xbb\xbf') or b'\r' in raw or not raw.endswith(b'\n'):
        raise ValueError('Standard CSV must be UTF-8 without BOM and use LF line endings')
    text = raw.decode('utf-8', errors='strict')
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError('Missing CSV header') from exc
    if tuple(header) != COLUMNS:
        raise ValueError('Standard CSV header differs from contract')
    count, ids = 0, set()
    for values in reader:
        if len(values) != len(COLUMNS):
            raise ValueError('Malformed CSV row')
        row = dict(zip(COLUMNS, values))
        if row['batch_id'] != batch_id or not ID_PATTERN.fullmatch(row['attraction_id']):
            raise ValueError('CSV contains wrong batch or invalid attraction ID')
        if row['attraction_id'] in ids:
            raise ValueError('Duplicate attraction ID in CSV')
        ids.add(row['attraction_id'])
        for key, typ in [('type_codes', list), ('source_refs', dict)]:
            parsed = json.loads(row[key])
            if not isinstance(parsed, typ):
                raise ValueError('Invalid ' + key)
        if row['grade_status'] not in ('rated', 'unrated', 'unknown', 'conflict'):
            raise ValueError('Unknown grade status')
        if row['price_form'] not in ('unknown', 'free', 'exact', 'range', 'from', 'conflict'):
            raise ValueError('Unknown price form')
        count += 1
    if count <= 0 or count != expected_count:
        raise ValueError(f'CSV row count mismatch: observed {count}, manifest {expected_count}')
    # Standard CSV must have exactly one physical line per record.
    if raw.count(b'\n') != count + 1:
        raise ValueError('Embedded line breaks in standard CSV')


def hdfs_cat(hdfs_binary: str, uri: str) -> bytes:
    return subprocess.run([hdfs_binary, 'dfs', '-cat', uri], check=True, stdout=subprocess.PIPE).stdout


def source_context(hdfs_binary: str, root: str, batch: str, uri: str) -> dict:
    """Verify immutable HDFS snapshot before either engine can run."""
    valid_id(batch)
    if not root.startswith('/') or root == '/' or '..' in root.split('/'):
        raise ValueError('Invalid HDFS_ROOT')
    if not uri.startswith('hdfs://') or not uri[7:].split('/', 1)[0]:
        raise ValueError('HDFS_URI must include scheme and authority')
    base = root.rstrip('/') + '/batches/' + batch
    paths = {
        'input': uri.rstrip('/') + base + '/input/attractions.csv',
        'manifest': uri.rstrip('/') + base + '/metadata/manifest.json',
        'dictionaries': uri.rstrip('/') + base + '/metadata/dictionaries.json',
    }
    manifest_raw = hdfs_cat(hdfs_binary, paths['manifest'])
    dictionary_raw = hdfs_cat(hdfs_binary, paths['dictionaries'])
    csv_raw = hdfs_cat(hdfs_binary, paths['input'])
    manifest = json.loads(manifest_raw)
    dictionaries = json.loads(dictionary_raw)
    if manifest.get('batch_id') != batch or manifest.get('contract_version') != '1.0':
        raise ValueError('Manifest identity/contract mismatch')
    if manifest.get('data_kind') not in ('test', 'real'):
        raise ValueError('Missing or invalid data_kind')
    if not isinstance(manifest.get('standard_count'), int) or manifest['standard_count'] <= 0:
        raise ValueError('Missing manifest standard_count')
    if not DIGEST_PATTERN.fullmatch(manifest.get('standard_sha256', '')):
        raise ValueError('Bad manifest standard SHA256')
    if hashlib.sha256(csv_raw).hexdigest() != manifest['standard_sha256']:
        raise ValueError('HDFS standard file SHA256 mismatch')
    if hashlib.sha256(dictionary_raw).hexdigest() != manifest.get('dictionaries_sha256'):
        raise ValueError('HDFS dictionaries SHA256 mismatch')
    if not isinstance(dictionaries.get('price_policies'), list):
        raise ValueError('Missing price_policies array')
    validate_csv_bytes(csv_raw, batch, manifest['standard_count'])
    return {'manifest': manifest, 'dictionaries': dictionaries, 'paths': paths,
            'hdfs_batch': uri.rstrip('/') + base}


def parse_jsonl(text: str, batch: str, engine: str) -> list[dict]:
    seen = set()
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get('batch_id') != batch or obj.get('engine') != engine:
            raise ValueError('Mixed batch or engine in statistics')
        if set(obj) != {'batch_id', 'engine', 'metric', 'dimensions', 'status', 'value'}:
            raise ValueError('Unexpected statistics record keys')
        dims = obj['dimensions']
        if not isinstance(dims, dict):
            raise ValueError('Malformed statistics dimensions')
        if obj['metric'] == 'attraction_count':
            scope = dims.get('scope')
            if scope not in COUNT_DIMENSIONS or set(dims) != set(COUNT_DIMENSIONS[scope]):
                raise ValueError('Invalid count dimension keys')
            if obj['status'] != 'ok' or not isinstance(obj['value'], dict) or set(obj['value']) != {'count'} or type(obj['value']['count']) is not int or obj['value']['count'] < 0:
                raise ValueError('Invalid count metric value')
        signature = (obj['metric'], canonical_json(dims))
        if signature in seen:
            raise ValueError('Duplicate metric/dimensions')
        seen.add(signature)
        result.append(obj)
    if not result:
        raise ValueError('Empty statistics results')
    return result


def output_files(root: Path, batch: str, engine: str, rows: list[dict], run: dict) -> Path:
    """Write one selected run per batch; never overwrite previous delivered run."""
    valid_id(batch)
    target = root / 'data' / 'results' / batch / engine
    target.mkdir(parents=True, exist_ok=True)
    jsonl = target / 'statistics.jsonl'
    info = target / 'run.json'
    if jsonl.exists() or info.exists():
        raise FileExistsError('Selected output already exists; review before replacing')
    content = ''.join(json_line(x) + '\n' for x in sorted(rows, key=lambda x: (x['metric'], canonical_json(x['dimensions']))))
    jsonl.write_text(content, encoding='utf-8', newline='\n')
    info.write_text(json.dumps(run, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    return target
