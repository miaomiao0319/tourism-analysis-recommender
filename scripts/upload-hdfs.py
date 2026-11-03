"""Publish one validated batch to HDFS using a unique staging directory."""
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.preflight import check
from cleaning.atlas_clean import ROOT


def upload(batch):
    check(batch)
    hadoop_home = os.environ.get('HADOOP_HOME')
    java_home = os.environ.get('JAVA_HOME')
    conf = os.environ.get('HADOOP_CONF_DIR')
    if not hadoop_home or not java_home or not conf:
        raise ValueError('Set HADOOP_HOME, JAVA_HOME and HADOOP_CONF_DIR')
    hdfs_root = os.environ.get('HDFS_ROOT', '/tourism')
    if not hdfs_root.startswith('/') or '..' in hdfs_root.split('/') or hdfs_root == '/':
        raise ValueError('Invalid HDFS_ROOT')
    binary = str(Path(hadoop_home) / 'bin/hdfs')
    def call(*args, capture=False):
        return subprocess.run([binary, 'dfs', *args], check=True, stdout=subprocess.PIPE if capture else None).stdout
    def exists(path):
        result = subprocess.run([binary, 'dfs', '-test', '-e', path])
        if result.returncode not in (0, 1):
            raise RuntimeError('HDFS path check failed')
        return result.returncode == 0
    meta = ROOT / 'data/metadata' / batch
    manifest = json.loads((meta / 'manifest.json').read_text(encoding='utf-8'))
    files = {'input/attractions.csv': ROOT / manifest['standard_file'],
             'metadata/manifest.json': meta / 'manifest.json',
             'metadata/dictionaries.json': meta / 'dictionaries.json'}
    parent = hdfs_root.rstrip('/') + '/batches'
    target = parent + '/' + batch
    def compare(base):
        for name, path in files.items():
            remote = call('-cat', base + '/' + name, capture=True)
            if hashlib.sha256(remote).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise ValueError('HDFS content mismatch: ' + name)
    if exists(target):
        compare(target)
        return {'batch_id': batch, 'status': 'already_present_verified', 'hdfs_path': target}
    call('-mkdir', '-p', parent)
    lock = parent + '/_upload_lock_' + batch
    call('-mkdir', lock)
    try:
        if exists(target):
            compare(target)
            return {'batch_id': batch, 'status': 'already_present_verified', 'hdfs_path': target}
        stage = parent + '/_staging_' + batch + '_' + uuid.uuid4().hex
        call('-mkdir', '-p', stage + '/input', stage + '/metadata')
        for name, path in files.items():
            call('-put', str(path), stage + '/' + name)
        compare(stage)
        if exists(target):
            raise FileExistsError('Batch appeared during staging; retained: ' + stage)
        call('-mv', stage, target)
        compare(target)
    finally:
        call('-rmdir', lock)
    return {'batch_id': batch, 'status': 'uploaded_verified', 'hdfs_path': target}


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--batch-id':
        raise SystemExit('Usage: python scripts/upload-hdfs.py --batch-id ID')
    print(json.dumps(upload(sys.argv[2]), ensure_ascii=False))
