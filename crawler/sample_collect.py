"""Bounded teaching collector; Python 3.11-compatible, curl required. No cleaning.

Run: python crawler/sample_collect.py NEW_OUTPUT_DIRECTORY
The project Scrapy environment remains a separate, unfinished task.
"""
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

AGENT = "TourismCourseSample/0.1 (educational bounded collection)"
TITLE = "张家口市区景点一览"
HEADERS = ["景点名称", "所在区", "门票(元)", "建议游玩", "特色标签"]
SOURCES = [
    ("zjk", "https://data.zjktravel.com", "/destinations/zhangjiakou/",
     "https://data.zjktravel.com/", "CC BY 4.0"),
    ("wikidata", "https://www.wikidata.org", "/wiki/Special:EntityData/Q2047427.json",
     "https://www.wikidata.org/wiki/Wikidata:Licensing", "CC0"),
]


def robots_allows(text, url):
    """RFC 9309 wildcard/longest-match handling for the collector user agent."""
    groups, agents, rules = [], [], []
    for line in text.splitlines() + ["User-agent: __end__"]:
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((key, value))
    agent = AGENT.split("/", 1)[0].lower()
    specific = [g for g in groups if agent in g[0]]
    selected = specific or [g for g in groups if "*" in g[0]]
    target = urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else "")
    matches = []
    for _, entries in selected:
        for key, pattern in entries:
            end = pattern.endswith("$")
            pattern = pattern[:-1] if end else pattern
            expression = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if end else "")
            if re.search(expression, target):
                matches.append((len(pattern.replace("*", "")), key == "allow"))
    return max(matches, default=(0, True))[1]


class ScenicTable(HTMLParser):
    """Select the first table after one exact h2; preserve cell text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading = None
        self.matches = 0
        self.waiting = False
        self.active = False
        self.finished = False
        self.cell = None
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.heading = []
        if tag == "table" and self.waiting and not self.finished:
            self.active = True
            self.waiting = False
        if self.active and tag == "tr":
            self.row = []
        if self.active and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self.heading is not None:
            if "".join(self.heading).strip() == TITLE:
                self.matches += 1
                self.waiting = True
            self.heading = None
        if self.active and tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        if self.active and tag == "tr" and self.row:
            self.rows.append(self.row)
        if self.active and tag == "table":
            self.active = False
            self.finished = True


def parse_html(body):
    parser = ScenicTable()
    parser.feed(body.decode("utf-8", errors="strict"))
    if parser.matches != 1 or not parser.finished or not parser.rows:
        raise ValueError("Target heading/table missing or duplicated")
    if parser.rows[0] != HEADERS:
        raise ValueError("Unexpected table headers")
    rows = parser.rows[1:11]
    if not rows or any(len(row) != 5 for row in rows):
        raise ValueError("Empty table or malformed row")
    return [dict(zip(["name_raw", "district_raw", "price_raw", "duration_raw", "tags_raw"], row))
            for row in rows]


def parse_entity(body):
    entity = json.loads(body)["entities"]["Q2047427"]
    if entity["id"] != "Q2047427" or "missing" in entity:
        raise ValueError("Unexpected/missing entity")
    return [{"source_item_id": entity["id"],
             "name_raw": entity.get("labels", {}).get("zh", {}).get("value"),
             "claims_raw": entity.get("claims", {}),
             "revision": entity["lastrevid"], "source_modified_at": entity["modified"]}]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def collect(output):
    output.mkdir(parents=True, exist_ok=False)
    run = {"started_at": datetime.now(timezone.utc).isoformat(), "data_kind": "real",
           "python": platform.python_version(), "tool": "stdlib HTMLParser/JSON + curl",
           "status": "in_progress", "requests": [], "sources": [],
           "scope": "one HTML table, at most 10 rows; one entity; no cleaning"}
    previews = []

    def download(url, stem):
        body_path = output / (stem + ".raw")
        header_path = output / (stem + ".headers")
        started = datetime.now(timezone.utc).isoformat()
        proc = subprocess.run(
            ["curl.exe" if sys.platform == "win32" else "curl", "--silent", "--show-error",
             "--max-time", "25", "--max-filesize", "3000000", "--compressed",
             "--user-agent", AGENT, "-D", str(header_path), "-o", str(body_path),
             "-w", "%{http_code}", url], capture_output=True, timeout=30)
        body = body_path.read_bytes() if body_path.exists() else b""
        record = {"url": url, "requested_at": started,
                  "collected_at": datetime.now(timezone.utc).isoformat(),
                  "http_status": proc.stdout.decode("ascii", errors="replace"),
                  "curl_exit": proc.returncode, "raw_ref": body_path.name,
                  "headers_ref": header_path.name, "sha256": hashlib.sha256(body).hexdigest(),
                  "bytes": len(body), "error": proc.stderr.decode("utf-8", errors="replace")}
        run["requests"].append(record)
        write_json(output / "run.json", run)
        if proc.returncode:
            raise RuntimeError("Request failed; see run.json")
        return record, body

    try:
        for sid, origin, path, license_url, license_name in SOURCES:
            rules, body = download(origin + "/robots.txt", sid + "-robots")
            if rules["http_status"] == "200":
                text = body.decode("utf-8-sig")
                if "user-agent:" not in text.lower():
                    raise ValueError("Invalid robots response; stop for review")
                if not robots_allows(text, origin + path) or not robots_allows(text, license_url):
                    raise ValueError("robots disallows requested path")
            elif rules["http_status"] != "404":
                raise ValueError("robots unresolved; stop for review")
            time.sleep(5)
            lic, lic_body = download(license_url, sid + "-license")
            if lic["http_status"] != "200" or license_name.lower() not in lic_body.decode("utf-8").lower():
                raise ValueError("License statement not confirmed")
            time.sleep(5)
            meta, raw = download(origin + path, sid)
            if meta["http_status"] != "200":
                raise ValueError("Non-200 response; no retries; respect Retry-After if present")
            rows = parse_html(raw) if sid == "zjk" else parse_entity(raw)
            run["sources"].append({"source_id": sid, "license": license_name,
                                   "license_url": license_url, "count": len(rows)})
            for index, row in enumerate(rows, 1):
                row.update(source_id=sid, source_url=meta["url"], raw_ref=meta["raw_ref"],
                           raw_locator=f"{TITLE}/row/{index}" if sid == "zjk" else "entities.Q2047427",
                           collected_at=meta["collected_at"], raw_sha256=meta["sha256"],
                           license=license_name, license_url=license_url,
                           attribution="张家口旅游数据百科 / 张家口美景国际旅行社" if sid == "zjk" else "Wikidata",
                           data_kind="real", standard_snapshot=False)
                previews.append(row)
        with (output / "preview.jsonl").open("x", encoding="utf-8") as stream:
            for row in previews:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        run["status"] = "success"
        run["preview_count"] = len(previews)
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = str(exc)
        raise
    finally:
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run.json", run)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: sample_collect.py NEW_OUTPUT_DIRECTORY")
    collect(Path(sys.argv[1]))
