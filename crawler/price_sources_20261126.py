"""Capture public 2026 ticket notices, with robots and response records."""
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from crawler.sample_collect import AGENT, robots_allows

URLS = {
    'beijing': 'https://www.beijing.gov.cn/fuwu/lqfw/gggs/202609/t20260917_4868383.html',
    'linyi': 'https://www.linyi.gov.cn/info/3442/496769.htm',
    'yichun': 'https://www.yc.gov.cn/ycsrmzf/c102114/202602/421813.shtml',
    'pingliang': 'https://www.pingliang.gov.cn/api-gateway/jpaas-publish-server/front/page/build/info?alias=defaultSet&infoId=d1dac3802c1a470faad1d2aab43e2552&url=%2Fzfxxgk%2Fbmxxgk%2Fktqwlj%2Ffdzdgknr%2Fggwhfw%2Flyfw%2Fart%2F2026%2Fart_d1dac3802c1a470faad1d2aab43e2552.html&xxgkFlg=xxgk',
}


def fetch(url, path):
    result = subprocess.run(['curl.exe' if sys.platform == 'win32' else 'curl', '--silent', '--show-error',
                             '--compressed', '--max-time', '30', '--max-filesize', '5000000',
                             '--user-agent', AGENT, '--output', str(path), '--write-out', '%{http_code}', url],
                            capture_output=True, text=True, timeout=35)
    if result.returncode:
        raise RuntimeError('Source request failed: ' + url)
    return result.stdout


def collect(output):
    output.mkdir(parents=True, exist_ok=False)
    run = {'status': 'in_progress', 'requests': [], 'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        for name, url in URLS.items():
            parsed = urlsplit(url)
            robots = parsed.scheme + '://' + parsed.netloc + '/robots.txt'
            robots_file = output / (name + '-robots.txt')
            status = fetch(robots, robots_file)
            if status not in ('200', '404'):
                raise ValueError('Robots request failed: ' + name)
            if status == '200' and not robots_allows(robots_file.read_text(encoding='utf-8-sig'), url):
                raise ValueError('Robots disallows: ' + name)
            time.sleep(2)
            path = output / (name + '.html')
            if fetch(url, path) != '200':
                raise ValueError('Source unavailable: ' + name)
            raw = path.read_bytes()
            run['requests'].append(dict(name=name, url=url, raw_ref=path.name,
                robots_status=status, robots_sha256=hashlib.sha256(robots_file.read_bytes()).hexdigest(),
                sha256=hashlib.sha256(raw).hexdigest(), collected_at=datetime.now(timezone.utc).isoformat()))
        run['status'] = 'success'
    except Exception as exc:
        run.update(status='failed', error=str(exc))
        raise
    finally:
        run['finished_at'] = datetime.now(timezone.utc).isoformat()
        (output / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    collect(Path(sys.argv[1]))
