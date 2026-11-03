"""Bounded acquisition of licensed geographic reference or raw ticket notes."""
import hashlib
import base64
import io
import json
import subprocess
import sys
import time
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from crawler.sample_collect import AGENT, robots_allows, write_json

SPECS = {
    "voyage_baoshan": ("https://en.wikivoyage.org", [
        ("license", "/wiki/Wikivoyage:Copyleft"),
        ("baoshan", "/wiki/Shanghai/Baoshan")], "creativecommons.org/licenses/by-sa/4.0"),
    "voyage_shanghai": ("https://en.wikivoyage.org", [
        ("license", "/wiki/Wikivoyage:Copyleft"),
        ("baoshan", "/wiki/Shanghai/Baoshan"),
        ("pudong", "/wiki/Shanghai/Pudong"),
        ("huangpu", "/wiki/Shanghai/Huangpu")], "creativecommons.org/licenses/by-sa/4.0"),
    "atlas_scopes": ("https://www.atlasofchina.com", [
        ("license", "/data/"), ("places", "/data/places.json"),
        ("sites", "/data/sites.json")], "CC BY 4.0"),
    "geo_wikidata": ("https://www.wikidata.org", [
        ("license", "/wiki/Wikidata:Licensing"),
        *[(qid, "/wiki/Special:EntityData/" + qid + ".json") for qid in
          ("Q16959", "Q571219", "Q573124", "Q989885", "Q874291", "Q571126", "Q1012419", "Q577713", "Q115594", "Q861035", "Q1012460")]], "CC0"),
    "voyage_prices": ("https://en.wikivoyage.org", [
        ("license", "/wiki/Wikivoyage:Copyleft"),
        ("jiuzhaigou", "/wiki/Jiuzhaigou_Nature_Reserve"),
        ("huangshan", "/wiki/Huangshan"),
        ("mount_tai", "/wiki/Mount_Tai")], "creativecommons.org/licenses/by-sa/4.0"),
    "divisions_npm": ("https://registry.npmjs.org", [
        ("metadata", "/cn-divisions/0.1.3"),
        ("package", "/cn-divisions/-/cn-divisions-0.1.3.tgz")], "MIT"),
    "divisions": ("https://raw.githubusercontent.com", [
        ("license", "/roy-tian/cn-divisions/master/LICENSE"),
        ("notice", "/roy-tian/cn-divisions/master/NOTICE.md"),
        ("divisions", "/roy-tian/cn-divisions/master/data/divisions.jsonl")], "MIT License"),
    "prices": ("https://data.zjktravel.com", [
        ("license", "/"), ("costs", "/data/costs/"),
        ("destinations", "/destinations/")], "CC BY 4.0"),
}


def collect(kind, output):
    origin, paths, marker = SPECS[kind]
    output.mkdir(parents=True, exist_ok=False)
    run = dict(status="in_progress", data_kind="real", supplement_kind=kind, requests=[],
               license=marker, started_at=datetime.now(timezone.utc).isoformat())

    def fetch(stem, path):
        body_path = output / (stem + ".raw")
        proc = subprocess.run(["curl.exe" if sys.platform == "win32" else "curl",
            "--silent", "--show-error", "--compressed", "--max-time", "60",
            "--max-filesize", "12000000", "--user-agent", AGENT,
            "--dump-header", str(output / (stem + ".headers")),
            "--output", str(body_path), "--write-out", "%{http_code}", origin + path],
            capture_output=True, timeout=65)
        body = body_path.read_bytes() if body_path.exists() else b""
        meta = dict(url=origin + path, raw_ref=body_path.name,
                    http_status=proc.stdout.decode("ascii", errors="replace"), curl_exit=proc.returncode,
                    bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                    collected_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    error=proc.stderr.decode("utf-8", errors="replace"))
        run["requests"].append(meta)
        write_json(output / "run.json", run)
        if proc.returncode or meta["http_status"] not in ("200", "404"):
            raise RuntimeError("Download failed; retain partial response, no retries")
        return meta, body

    try:
        meta, body = fetch("robots", "/robots.txt")
        if meta["http_status"] == "200":
            rules = body.decode("utf-8-sig")
            registry_route = kind == "divisions_npm" and json.loads(rules).get("_id") == "robots.txt"
            if registry_route:
                run["robots_note"] = "npm registry routes /robots.txt to metadata of the package named robots.txt; not a robots rule file. Only fixed package-distribution API endpoints requested."
            elif "user-agent:" not in rules.lower() or not all(robots_allows(rules, origin + path) for _, path in paths):
                raise ValueError("Unresolved/disallowed robots rules")
        for stem, path in paths:
            time.sleep(5)
            meta, body = fetch(stem, path)
            if meta["http_status"] != "200":
                raise ValueError("Required supplement unavailable")
            if stem == "metadata" and json.loads(body).get("license") != "MIT":
                raise ValueError("Package license is not MIT")
            if stem == "license" and marker not in body.decode("utf-8"):
                raise ValueError("License not confirmed")
        if kind == "divisions_npm":
            metadata = json.loads((output / "metadata.raw").read_bytes())
            integrity = "sha512-" + base64.b64encode(hashlib.sha512(body).digest()).decode("ascii")
            if integrity != metadata["dist"]["integrity"]:
                raise ValueError("Package integrity mismatch")
            run["members"] = []
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                for member_name, local_name in [("LICENSE", "license.raw"), ("NOTICE.md", "notice.raw"), ("data/divisions.jsonl", "divisions.raw")]:
                    member = archive.getmember("package/" + member_name)
                    if not member.isfile() or member.size > 12000000:
                        raise ValueError("Unsafe package member")
                    data = archive.extractfile(member).read()
                    (output / local_name).write_bytes(data)
                    run["members"].append(dict(raw_ref=local_name, member=member.name, sha256=hashlib.sha256(data).hexdigest()))
            if "MIT License" not in (output / "license.raw").read_text(encoding="utf-8"):
                raise ValueError("Package license file not confirmed")
            run["package_version"] = metadata["version"]
        run["status"] = "success"
    except Exception as exc:
        run.update(status="failed", error=str(exc))
        raise
    finally:
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run.json", run)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in SPECS:
        raise SystemExit("Usage: python -m crawler.supplement_collect divisions|divisions_npm|prices NEW_DIRECTORY")
    collect(sys.argv[1], Path(sys.argv[2]))
