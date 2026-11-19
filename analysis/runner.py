"""Run one actual Hadoop Streaming or PySpark job and preserve its provenance.

No implicit install, no NameNode formatting, no writes to immutable inputs,
no overwrites of previous HDFS run directories or local selected results.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from analysis.common import (hdfs_cat, json_line, output_files,
                             parse_jsonl, source_context, utc_now, valid_id)
from analysis.mapreduce.converter import convert_output
from database.statistics_check import reconcile_counts

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_RE = re.compile(r'application_\d+_\d+')
JAVA_11_RE = re.compile(r'(?:openjdk|java) version "11(?:[.\"])')


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.resolve()


def hdfs_exists(binary: str, path: str) -> bool:
    proc = subprocess.run([binary, 'dfs', '-test', '-e', path], check=False)
    if proc.returncode not in (0, 1):
        raise RuntimeError('HDFS existence check failed')
    return proc.returncode == 0


def execute(command, *, env, log_file: Path) -> str:
    result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Job exited {result.returncode}, inspect {log_file}')
    return result.stdout


def require_runtime_versions(*, engine: str, java: str, hadoop: str, python: str, env: dict) -> None:
    """Reject a look-alike local installation before it can touch HDFS outputs."""
    java_version = subprocess.run([java, '-version'], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                  errors='replace', check=True).stdout
    if not JAVA_11_RE.search(java_version):
        raise RuntimeError('Java 11 is required for this project runtime')
    hadoop_version = subprocess.run([hadoop, 'version'], env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                    errors='replace', check=True).stdout
    if not re.search(r'^Hadoop 3\.4\.3\s*$', hadoop_version, re.MULTILINE):
        raise RuntimeError('Hadoop 3.4.3 is required for this project runtime')
    if engine == 'spark_sql':
        pyspark_version = subprocess.run(
            [python, '-c', 'import pyspark; print(pyspark.__version__)'], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace', check=True,
        ).stdout.strip()
        if pyspark_version != '3.5.8':
            raise RuntimeError('PySpark 3.5.8 is required for this project runtime')


def verified_stat_rows(rows: list[dict], *, batch: str, engine: str, count: int, policies: list) -> None:
    validated = parse_jsonl(''.join(json_line(r) + '\n' for r in rows), batch, engine)
    if len(validated) != len(rows):
        raise ValueError('Mismatch in result row count')
    for scope in ('city', 'grade'):
        subset = [r for r in rows if r['metric'] == 'attraction_count' and r['dimensions']['scope'] == scope]
        if sum(r['value']['count'] for r in subset) != count:
            raise ValueError(scope + ' counts do not sum to manifest count')
    if engine == 'spark_sql':
        count_scopes = {r['dimensions']['scope'] for r in rows if r['metric'] == 'attraction_count'}
        if count_scopes != {'all', 'province', 'city', 'grade', 'city_grade', 'type'}:
            raise ValueError('Missing required Spark count scopes')
        quality = [r for r in rows if r['metric'] == 'data_quality' and r['dimensions'] == {'scope': 'all'}]
        if len(quality) != 1 or quality[0]['value'].get('standard_count') != count:
            raise ValueError('Missing/inconsistent Spark data quality')
        for metric in ('price_summary', 'price_histogram'):
            relevant = [r for r in rows if r['metric'] == metric]
            if not relevant:
                raise ValueError('Missing Spark price status metric: ' + metric)
            if not policies and (len(relevant) != 1 or relevant[0]['status'] != 'pending_policy' or relevant[0]['value'] is not None):
                raise ValueError('No policies: price metric must be pending_policy')


def make_analysis_zip(runtime_folder: Path):
    """Distribute code for Spark's Python imports without adding Hadoop jars."""
    archive = runtime_folder / 'analysis_src.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for p in (ROOT / 'analysis').rglob('*.py'):
            z.write(p, p.relative_to(ROOT))
    return archive


def run(engine: str, batch: str, run_id: str) -> dict:
    if engine not in ('mapreduce', 'spark_sql'):
        raise ValueError('Only mapreduce or spark_sql supported')
    valid_id(batch); valid_id(run_id)
    env = dict(os.environ)
    home = Path(env['HADOOP_HOME']).expanduser().resolve(strict=True)
    hdfs = str(require_file(home / 'bin/hdfs'))
    hadoop = str(require_file(home / 'bin/hadoop'))
    yarn = str(require_file(home / 'bin/yarn'))
    java = str(require_file(Path(env['JAVA_HOME']) / 'bin/java'))
    if not Path(env['HADOOP_CONF_DIR']).is_dir():
        raise ValueError('HADOOP_CONF_DIR must point to actual Hadoop configuration')
    venv = ROOT / '.venv' / 'bin'
    python = str(require_file(venv / 'python'))
    require_runtime_versions(engine=engine, java=java, hadoop=hadoop, python=python, env=env)
    hdfs_uri = env.get('HDFS_URI', 'hdfs://localhost:9000')
    context = source_context(hdfs, env.get('HDFS_ROOT', '/tourism'), batch, hdfs_uri)
    manifest = context['manifest']
    hdfs_output = context['hdfs_batch'] + '/runs/' + run_id + '/' + engine
    if hdfs_exists(hdfs, hdfs_output):
        raise FileExistsError('HDFS run path exists; choose a fresh run-id')
    selected = ROOT / 'data' / 'results' / batch / engine
    if (selected / 'statistics.jsonl').exists() or (selected / 'run.json').exists():
        raise FileExistsError('Selected result already exists; review before replacing')
    runtime = ROOT / '.runtime' / 'analysis' / batch / run_id / engine
    runtime.mkdir(parents=True, exist_ok=False)
    log_file = runtime / 'job.log'
    started_at = utc_now()
    raw_dir = hdfs_output + '/raw'
    if engine == 'mapreduce':
        import glob
        streaming_jars = glob.glob(str(home / 'share/hadoop/tools/lib/hadoop-streaming-*.jar'))
        if len(streaming_jars) != 1:
            raise FileNotFoundError('Expected exactly one Hadoop Streaming jar')
        files = [ROOT / 'analysis/mapreduce/mapper.py', ROOT / 'analysis/mapreduce/reducer.py']
        command = [hadoop, 'jar', streaming_jars[0],
                   '-D', 'mapreduce.framework.name=yarn', '-D', 'mapreduce.job.reduces=1',
                   '-D', 'stream.non.zero.exit.is.failure=true',
                   '-files', ','.join(str(p.resolve()) for p in files),
                   '-mapper', f'{python} mapper.py --batch-id {batch}',
                   '-reducer', f'{python} reducer.py',
                   '-input', context['paths']['input'], '-output', raw_dir]
    else:
        spark_submit = str(require_file(venv / 'spark-submit'))
        env['PYSPARK_PYTHON'] = python
        env['PYSPARK_DRIVER_PYTHON'] = python
        env['PYTHONPATH'] = str(ROOT) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        bundle = make_analysis_zip(runtime)
        command = [spark_submit, '--master', 'local[2]', '--py-files', str(bundle),
                   str(ROOT / 'analysis/spark/job.py'), '--batch-id', batch,
                   '--input-uri', context['paths']['input'],
                   '--dictionaries-uri', context['paths']['dictionaries'], '--output-uri', raw_dir]
    env['PYTHONIOENCODING'] = 'utf-8'
    stdout = execute(command, env=env, log_file=log_file)
    application_id = None
    yarn_counters = {}
    if engine == 'mapreduce':
        app_ids = APPLICATION_RE.findall(stdout)
        if not app_ids:
            raise RuntimeError('No YARN application ID in Hadoop output: cannot validate real YARN run')
        application_id = app_ids[-1]
        status = subprocess.run([yarn, 'application', '-status', application_id], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace', check=True).stdout
        (runtime / 'yarn-status.log').write_text(status, encoding='utf-8')
        if not re.search(r'Final-State\s*:\s*SUCCEEDED', status):
            raise RuntimeError('YARN application final state is not SUCCEEDED')
        for label in ('Map input records', 'Map output records', 'Reduce input groups', 'Reduce output records'):
            matched = re.search(r'^\s*' + re.escape(label) + r'\s*=\s*(\d+)\s*$', stdout, re.MULTILINE)
            if matched:
                yarn_counters[label] = int(matched.group(1))
    raw = hdfs_cat(hdfs, raw_dir + '/part-*').decode('utf-8')
    if engine == 'mapreduce':
        rows = convert_output(raw, batch)
    else:
        rows = parse_jsonl(raw, batch, engine)
    verified_stat_rows(rows, batch=batch, engine=engine,
                       count=manifest['standard_count'],
                       policies=context['dictionaries']['price_policies'])
    run_data = {
        'batch_id': batch, 'engine': engine, 'run_id': run_id,
        'contract_version': manifest['contract_version'],
        'data_kind': manifest['data_kind'],
        'input_sha256': manifest['standard_sha256'],
        'dictionaries_sha256': manifest['dictionaries_sha256'],
        'input_uri': context['paths']['input'],
        'metadata_uri': context['paths']['manifest'],
        'raw_output_uri': raw_dir,
        'execution': command, 'started_at': started_at, 'finished_at': utc_now(),
        'status': 'succeeded', 'yarn_application_id': application_id,
        'yarn_counters': yarn_counters if engine == 'mapreduce' else None,
        'local_job_log': str(log_file.relative_to(ROOT)),
        'count_checks': 'city_and_grade_sums_passed',
        'cross_engine_reconciliation': 'not_run_yet',
        'standard_count': manifest['standard_count'],
    }
    target = output_files(ROOT, batch, engine, rows, run_data)
    return {'batch_id': batch, 'engine': engine, 'status': 'local_results_written',
            'result_folder': str(target), 'run_id': run_id, 'application_id': application_id}


def reconcile(batch: str):
    valid_id(batch)
    from database.statistics_check import reconcile_counts, validate_run_identity
    paths = {name: ROOT / 'data' / 'results' / batch / name for name in ('mapreduce', 'spark_sql')}
    runs = {name: json.loads((dir / 'run.json').read_text(encoding='utf-8')) for name, dir in paths.items()}
    records = {name: parse_jsonl((dir / 'statistics.jsonl').read_text(encoding='utf-8'), batch, name)
               for name, dir in paths.items()}
    # Re-verify the immutable *real HDFS* manifest rather than trusting either run's self-reported identity.
    home = Path(os.environ['HADOOP_HOME']).expanduser().resolve(strict=True)
    hdfs = str(require_file(home / 'bin/hdfs'))
    context = source_context(hdfs, os.environ.get('HDFS_ROOT', '/tourism'), batch,
                             os.environ.get('HDFS_URI', 'hdfs://localhost:9000'))
    manifest = context['manifest']
    validate_run_identity(manifest, runs['mapreduce'], runs['spark_sql'])
    if runs['mapreduce']['status'] != 'succeeded' or runs['spark_sql']['status'] != 'succeeded':
        raise ValueError('Both engine runs must have actually succeeded')
    if runs['mapreduce']['data_kind'] != runs['spark_sql']['data_kind']:
        raise ValueError('Engines disagree on data kind')
    if (runs['mapreduce']['dictionaries_sha256'] != runs['spark_sql']['dictionaries_sha256']
            or runs['mapreduce']['dictionaries_sha256'] != manifest['dictionaries_sha256']):
        raise ValueError('Engines used different dictionaries or differ from HDFS manifest')
    total = runs['mapreduce']['standard_count']
    if total != runs['spark_sql']['standard_count'] or total != manifest['standard_count']:
        raise ValueError('Engines disagree on manifest count')
    checked = reconcile_counts(records['mapreduce'], records['spark_sql'], batch, total)
    output = ROOT / 'data' / 'results' / batch / 'reconciliation.json'
    if output.exists():
        raise FileExistsError('Reconciliation already exists; avoid overwriting audit evidence')
    report = {'batch_id': batch, 'timestamp': utc_now(), 'data_kind': runs['mapreduce']['data_kind'],
              'mapreduce_run_id': runs['mapreduce']['run_id'], 'spark_run_id': runs['spark_sql']['run_id'],
              'input_sha256': manifest['standard_sha256'], 'dictionaries_sha256': runs['mapreduce']['dictionaries_sha256'],
              **checked, 'ready_for_import': False,
              'reason': 'Count reconciliation alone cannot authorize MySQL batch publication; A must validate full metrics and provenance'}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['mapreduce', 'spark_sql', 'reconcile'])
    parser.add_argument('--batch-id', required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.action == 'reconcile':
        print(json.dumps(reconcile(args.batch_id), ensure_ascii=False))
    else:
        if not args.run_id:
            parser.error('--run-id is required for engine runs')
        print(json.dumps(run(args.action, args.batch_id, args.run_id), ensure_ascii=False))


if __name__ == '__main__':
    main()
