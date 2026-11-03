"""Receive Atlas of China's explicitly licensed CSV exports, without cleaning.

Run: python -m crawler.atlas_collect NEW_OUTPUT_DIRECTORY
Original CSV cells are never rewritten. Counts describe publisher records, not
verified attraction entities, official grades, visitor demand or ticket prices.
"""
import csv
import hashlib
import io
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from crawler.sample_collect import AGENT, robots_allows, write_json

ORIGIN = "https://www.atlasofchina.com"
FILES = {"regions": "regions.csv", "sites": "sites.csv",
         "featured": "places.csv", "5a": "5a-scenic-areas.csv"}
PROVINCES = dict(zip(
    "110000 120000 130000 140000 150000 210000 220000 230000 310000 320000 330000 340000 350000 360000 370000 410000 420000 430000 440000 450000 460000 500000 510000 520000 530000 540000 610000 620000 630000 640000 650000".split(),
    "北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆".split()))


def read_csv(body, required):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True)
    fields = reader.fieldnames
    if not fields or len(set(fields)) != len(fields) or not set(required) <= set(fields):
        raise ValueError("CSV headers missing, changed or duplicated")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("Empty or malformed CSV; retain raw response for review")
    return rows


def coverage(rows):
    counts = Counter(row["region_id"] for row in rows)
    scenic = Counter(row["region_id"] for row in rows
                     if {"4A", "5A"} & set(row["designations"].split("; ")))
    cities = {code: set() for code in PROVINCES}
    for row in rows:
        if row["region_id"] in cities and row["city"]:
            cities[row["region_id"]].add(row["city"])
    return {
        "total_source_rows": len(rows),
        "mainland_source_rows": sum(counts[code] for code in PROVINCES),
        "covered_target_regions": sum(counts[code] > 0 for code in PROVINCES),
        "mainland_scenic_label_rows": sum(scenic[code] for code in PROVINCES),
        "scenic_label_target_regions": sum(scenic[code] > 0 for code in PROVINCES),
        "other_region_counts": {code: count for code, count in counts.items() if code not in PROVINCES},
        "targets": [{"region_id": code, "name": name, "source_rows": counts[code],
                     "scenic_label_rows": scenic[code],
                     "distinct_nonempty_city_strings": len(cities[code])}
                    for code, name in PROVINCES.items()],
        "blank_name_rows": sum(not row["name_zh"] for row in rows),
        "blank_city_rows": sum(not row["city"] for row in rows),
        "designations_raw_counts": dict(Counter(row["designations"] for row in rows)),
        "verification_dates_raw_counts": dict(Counter(row["verified"] for row in rows)),
        "duplicate_id_observations": len(rows) - len({row["id"] for row in rows}),
        "both_4a_and_5a_label_rows": sum({"4A", "5A"} <= set(row["designations"].split("; ")) for row in rows),
        "cleaning_executed": False,
        "count_meaning": "Publisher CSV rows grouped by unchanged region_id; city strings are not standardized; no deduplication or grade verification.",
    }


def collect(output):
    output.mkdir(parents=True, exist_ok=False)
    run = {"source_id": "atlas_of_china", "data_kind": "real", "status": "in_progress",
           "started_at": datetime.now(timezone.utc).isoformat(), "requests": [],
           "license": "CC BY 4.0", "license_url": ORIGIN + "/data/",
           "attribution": "Atlas of China — https://www.atlasofchina.com/data/",
           "cleaning_executed": False, "standard_snapshot": False,
           "date_limit": "2026-10-31; verified is the publisher's checking date, not proof of historical validity"}

    def download(path, stem):
        url = ORIGIN + path
        body_path, headers = output / (stem + ".raw"), output / (stem + ".headers")
        proc = subprocess.run([
            "curl.exe" if sys.platform == "win32" else "curl", "--silent", "--show-error",
            "--compressed", "--max-time", "60", "--max-filesize", "12000000",
            "--user-agent", AGENT, "--dump-header", str(headers),
            "--output", str(body_path), "--write-out", "%{http_code}", url],
            capture_output=True, timeout=65)
        body = body_path.read_bytes() if body_path.exists() else b""
        record = {"url": url, "raw_ref": body_path.name, "headers_ref": headers.name,
                  "collected_at": datetime.now(timezone.utc).isoformat(),
                  "http_status": proc.stdout.decode("ascii", errors="replace"),
                  "curl_exit": proc.returncode, "bytes": len(body),
                  "sha256": hashlib.sha256(body).hexdigest(),
                  "error": proc.stderr.decode("utf-8", errors="replace")}
        run["requests"].append(record)
        write_json(output / "run.json", run)
        if proc.returncode or record["http_status"] not in ("200", "404"):
            raise RuntimeError("Request failed; no automatic retry; see run.json")
        return record, body

    try:
        meta, body = download("/robots.txt", "robots")
        paths = ["/data/"] + ["/data/" + name for name in FILES.values()]
        if meta["http_status"] == "200":
            rules = body.decode("utf-8-sig")
            if "user-agent:" not in rules.lower() or not all(robots_allows(rules, ORIGIN + path) for path in paths):
                raise ValueError("Unresolved/disallowed robots rule; stop")
        time.sleep(5)
        meta, body = download("/data/", "license")
        text = body.decode("utf-8")
        if meta["http_status"] != "200" or "creativecommons.org/licenses/by/4.0/" not in text or "CC BY 4.0" not in text:
            raise ValueError("Explicit license statement not found")
        run["files"] = {}
        for key, name in FILES.items():
            time.sleep(5)
            meta, body = download("/data/" + name, key)
            if meta["http_status"] != "200":
                raise ValueError("Data file unavailable")
            required = ["id", "name_zh"] if key == "regions" else ["region_id", "name_zh"]
            if key in ("sites", "featured"):
                required += ["id", "city", "designations", "verified"]
            rows = read_csv(body, required)
            run["files"][key] = {"raw_ref": meta["raw_ref"], "row_count": len(rows),
                                  "columns": list(rows[0]), "sha256": meta["sha256"]}
            if key in ("sites", "featured"):
                write_json(output / (key + "-coverage.json"), coverage(rows))
        run["status"] = "success"
    except Exception as exc:
        run["status"], run["error"] = "failed", str(exc)
        raise
    finally:
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run.json", run)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m crawler.atlas_collect NEW_OUTPUT_DIRECTORY")
    collect(Path(sys.argv[1]))
