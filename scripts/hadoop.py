"""Single-node HDFS/YARN lifecycle. Never format an existing runtime."""
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

from hadoop_guard import check

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime' / 'hadoop'
CONF = RUNTIME / 'conf'
DAEMON_CLASSES = {'namenode': 'org.apache.hadoop.hdfs.server.namenode.NameNode',
    'datanode': 'org.apache.hadoop.hdfs.server.datanode.DataNode',
    'secondarynamenode': 'org.apache.hadoop.hdfs.server.namenode.SecondaryNameNode',
    'resourcemanager': 'org.apache.hadoop.yarn.server.resourcemanager.ResourceManager',
    'nodemanager': 'org.apache.hadoop.yarn.server.nodemanager.NodeManager'}


def daemon_running(name):
    user = pwd.getpwuid(os.geteuid()).pw_name
    pidfile = RUNTIME / 'pids' / ('hadoop-' + user + '-' + name + '.pid')
    if not pidfile.exists():
        return False
    value = pidfile.read_text(encoding='ascii').strip()
    if not value.isdecimal() or int(value) <= 1:
        raise ValueError('Invalid PID file: ' + str(pidfile))
    proc = Path('/proc') / value / 'cmdline'
    if not proc.exists():
        raise ValueError('Stale PID file; inspect before continuing: ' + str(pidfile))
    if DAEMON_CLASSES[name].encode() not in proc.read_bytes():
        raise ValueError('PID belongs to an unexpected process: ' + str(pidfile))
    return True


def command(args, env, capture=False):
    return subprocess.run(args, env=env, check=True, stdout=subprocess.PIPE if capture else None).stdout


def config_file(path, values):
    tree = ET.Element('configuration')
    for name, value in values.items():
        entry = ET.SubElement(tree, 'property')
        ET.SubElement(entry, 'name').text = name
        ET.SubElement(entry, 'value').text = str(value)
    ET.ElementTree(tree).write(path, encoding='utf-8', xml_declaration=True)


def ensure_support_files(home):
    for name in ('capacity-scheduler.xml', 'log4j.properties'):
        destination = CONF / name
        if not destination.exists():
            shutil.copyfile(home / 'etc/hadoop' / name, destination)


def run(action):
    java = Path(os.environ['JAVA_HOME']).resolve(strict=True)
    home = Path(os.environ['HADOOP_HOME']).resolve(strict=True)
    hdfs, yarn = str(home / 'bin/hdfs'), str(home / 'bin/yarn')
    runtime = RUNTIME.resolve()
    if not runtime.is_relative_to(ROOT.resolve()) or not runtime.is_relative_to((ROOT / '.runtime').resolve()):
        raise ValueError('Runtime must stay inside the project')
    env = dict(os.environ, JAVA_HOME=str(java), HADOOP_CONF_DIR=str(CONF),
        HADOOP_LOG_DIR=str(RUNTIME / 'logs'), HADOOP_PID_DIR=str(RUNTIME / 'pids'),
        YARN_LOG_DIR=str(RUNTIME / 'logs'), YARN_PID_DIR=str(RUNTIME / 'pids'),
        HADOOP_HEAPSIZE_MAX='512m')
    if action == 'init':
        print(check(ROOT, java, home), flush=True)
        # mkdir without exist_ok is an additional guard against concurrent initialization.
        RUNTIME.mkdir(parents=True, exist_ok=False)
        for name in ('conf', 'logs', 'pids', 'name', 'data', 'tmp'):
            (RUNTIME / name).mkdir()
        config_file(CONF / 'core-site.xml', {'fs.defaultFS': 'hdfs://localhost:9000', 'hadoop.tmp.dir': RUNTIME / 'tmp'})
        config_file(CONF / 'hdfs-site.xml', {'dfs.replication': '1', 'dfs.namenode.name.dir': (RUNTIME / 'name').as_uri(),
            'dfs.datanode.data.dir': 'file://' + str(RUNTIME / 'data'), 'dfs.namenode.http-address': '127.0.0.1:9870'})
        config_file(CONF / 'mapred-site.xml', {'mapreduce.framework.name': 'yarn',
            'mapreduce.application.classpath': '$HADOOP_MAPRED_HOME/share/hadoop/mapreduce/*:$HADOOP_MAPRED_HOME/share/hadoop/mapreduce/lib/*'})
        config_file(CONF / 'yarn-site.xml', {'yarn.nodemanager.aux-services': 'mapreduce_shuffle',
            'yarn.resourcemanager.hostname': 'localhost', 'yarn.resourcemanager.webapp.address': '127.0.0.1:8088',
            'yarn.nodemanager.webapp.address': '127.0.0.1:8042',
            'yarn.nodemanager.env-whitelist': 'JAVA_HOME,HADOOP_COMMON_HOME,HADOOP_HDFS_HOME,HADOOP_CONF_DIR,CLASSPATH_PREPEND_DISTCACHE,HADOOP_YARN_HOME,HADOOP_HOME,PATH,LANG,TZ,HADOOP_MAPRED_HOME'})
        ensure_support_files(home)
        command([hdfs, 'namenode', '-format', '-nonInteractive'], env)
        return
    if not (RUNTIME / 'name/current/VERSION').is_file():
        raise ValueError('No initialized NameNode metadata; start/stop cannot format it')
    daemons = [(hdfs, 'namenode'), (hdfs, 'datanode'), (hdfs, 'secondarynamenode'),
               (yarn, 'resourcemanager'), (yarn, 'nodemanager')]
    if action in ('start', 'stop'):
        if action == 'start':
            ensure_support_files(home)
            hdfs_config = CONF / 'hdfs-site.xml'
            hdfs_tree = ET.parse(hdfs_config)
            for prop in hdfs_tree.getroot().findall('property'):
                if prop.findtext('name') == 'dfs.datanode.data.dir' and prop.findtext('value') == (RUNTIME / 'data').as_uri():
                    prop.find('value').text = 'file://' + str(RUNTIME / 'data')
                    hdfs_tree.write(hdfs_config, encoding='utf-8', xml_declaration=True)
            path = CONF / 'yarn-site.xml'
            tree = ET.parse(path)
            if not any(p.findtext('name') == 'yarn.nodemanager.webapp.address' for p in tree.getroot().findall('property')):
                prop = ET.SubElement(tree.getroot(), 'property')
                ET.SubElement(prop, 'name').text = 'yarn.nodemanager.webapp.address'
                ET.SubElement(prop, 'value').text = '127.0.0.1:8042'
                tree.write(path, encoding='utf-8', xml_declaration=True)
        for binary, name in (daemons if action == 'start' else reversed(daemons)):
            running = daemon_running(name)
            if (action == 'start' and running) or (action == 'stop' and not running):
                print(name + (' already running' if running else ' already stopped'), flush=True)
                continue
            if action == 'start':
                with (RUNTIME / 'logs/launcher.log').open('ab') as log:
                    subprocess.run(['nohup', binary, '--daemon', action, name], env=env, check=True,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            else:
                command([binary, '--daemon', action, name], env)
        return
    if action != 'status':
        raise ValueError('Expected init, start, status or stop')
    report = command([hdfs, 'dfsadmin', '-report'], env, True).decode()
    if 'Live datanodes (1)' not in report:
        raise ValueError('DataNode is not live; inspect report')
    command([hdfs, 'dfs', '-ls', '/'], env)
    nodes = command([yarn, 'node', '-list'], env, True).decode()
    if 'RUNNING' not in nodes:
        raise ValueError('No running NodeManager')
    remote = '/tmp/tourism-check-' + uuid.uuid4().hex
    with tempfile.NamedTemporaryFile() as local:
        local.write(b'tourism-hdfs-check\n'); local.flush()
        command([hdfs, 'dfs', '-mkdir', '-p', '/tmp'], env)
        command([hdfs, 'dfs', '-put', local.name, remote], env)
        try:
            if command([hdfs, 'dfs', '-cat', remote], env, True) != b'tourism-hdfs-check\n':
                raise ValueError('HDFS readback mismatch')
        finally:
            command([hdfs, 'dfs', '-rm', remote], env)
    print('DataNode, NodeManager and HDFS readback verified')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: hadoop.py init|start|status|stop')
    run(sys.argv[1])
