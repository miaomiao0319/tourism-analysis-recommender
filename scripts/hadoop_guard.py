"""Conservative, read-only checks before first HDFS initialization."""
import json
import os
import socket
import subprocess
from pathlib import Path


def check(root, java_home, hadoop_home):
    root = Path(root).resolve(strict=True)
    runtime = root / '.runtime' / 'hadoop'
    base = (root / '.runtime').resolve()
    if not base.is_relative_to(root) or not runtime.resolve().is_relative_to(base):
        raise ValueError('Hadoop runtime escapes the project runtime directory')
    if runtime.exists() and any(runtime.iterdir()):
        raise FileExistsError('Hadoop runtime already contains data; do not initialize')
    java = Path(java_home) / 'bin/java'
    hdfs = Path(hadoop_home) / 'bin/hdfs'
    env = dict(os.environ, JAVA_HOME=str(java_home))
    j = subprocess.run([str(java), '-version'], capture_output=True, text=True, check=True)
    if 'version "11.' not in j.stderr:
        raise ValueError('Java 11 required')
    h = subprocess.run([str(hdfs), 'version'], capture_output=True, text=True, check=True, env=env)
    if not h.stdout.startswith('Hadoop 3.4.3\n'):
        raise ValueError('Hadoop 3.4.3 required')
    busy = []
    for port in (9000, 9870, 8088, 8032, 8042):
        with socket.socket() as listener:
            try:
                listener.bind(('127.0.0.1', port))
            except OSError:
                busy.append(port)
    if busy:
        raise OSError('Required local ports unavailable: ' + ', '.join(map(str, busy)))
    return {'project_root': str(root), 'runtime': str(runtime), 'java': j.stderr.splitlines()[0],
            'hadoop': h.stdout.splitlines()[0], 'ports_checked': [9000, 9870, 8088, 8032, 8042],
            'initialized': False, 'read_only': True}


if __name__ == '__main__':
    print(json.dumps(check(Path(__file__).resolve().parents[1], os.environ['JAVA_HOME'], os.environ['HADOOP_HOME']), ensure_ascii=False, indent=2))
