"""Create the downloadable preview from the actual demo HTTP responses and Vue UI."""
import argparse
import base64
import gzip
import itertools
import json
import subprocess
from pathlib import Path

from backend.app import create_app
from backend.app.services.recommender import MODE_MATRICES
from scripts.web_sample import BATCH, ROWS, SampleRepository

ROOT = Path(__file__).resolve().parents[1]
AMOUNTS = ["0", "59.99", "60", "69.99", "70", "100"]


def recordings():
    http = create_app({"ACTIVE_BATCH_ID": BATCH, "TESTING": True}, SampleRepository()).test_client()
    dataset = http.get("/api/v1/dataset").get_json()
    dictionaries = dataset["data"]["dictionaries"]
    regions = {r["key"]: r["level"] + "_key" for r in dictionaries["regions"]}
    price = dictionaries["price_policies"][0]
    results = {}
    for region, tag, mode, amount in itertools.product(["", *regions], ["", *(t["code"] for t in dictionaries["types"])],
                                                       MODE_MATRICES, ["", *AMOUNTS]):
        if not (region or tag or amount):
            continue
        body = dict(batch_id=BATCH, mode=mode, type_codes=[tag] if tag else [])
        if region:
            body[regions[region]] = region
        if amount:
            body["budget"] = {"amount": amount, "currency": price["currency"], "price_policy_id": price["id"]}
        response = http.post("/api/v1/recommendations", json=body)
        if response.status_code != 200:
            raise ValueError(response.get_json())
        results["|".join((region, tag, mode, amount))] = response.get_json()
    details = {row["attraction_id"]: http.get("/api/v1/attractions/" + row["attraction_id"],
               query_string={"batch_id": BATCH}).get_json() for row in ROWS}
    return dict(amounts=AMOUNTS, dataset=dataset, details=details, results=results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    out = parser.parse_args().output
    subprocess.run(["npm", "run", "build", "--", "--mode", "offline"], cwd=ROOT / "frontend", check=True)
    assets = ROOT / ".runtime/web-preview"
    js = (assets / "preview.iife.js").read_text().replace("</script", "<\\/script")
    css = (assets / "preview.css").read_text()
    blob = json.dumps(recordings(), ensure_ascii=False, separators=(",", ":")).encode()
    data = base64.b64encode(gzip.compress(blob, mtime=0)).decode()
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>山河图鉴 · 离线演示</title>'
            f'<style>{css}</style><body><div id="app">正在打开山河图鉴…</div>'
            f'<script type="application/octet-stream" id="recordings">{data}</script><script>{js}</script></body></html>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
