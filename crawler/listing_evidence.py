"""Extract original Wikivoyage listing parameters; never activate price policy."""
import hashlib
import json
import math
import sys
from html.parser import HTMLParser
from pathlib import Path

from cleaning.atlas_clean import dump_json, dump_lines


class Listings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []

    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get("data-mw")
        if not value:
            return
        payload = json.loads(value)
        for part in payload.get("parts", []):
            if not isinstance(part, dict) or "template" not in part:
                continue
            template = part["template"]
            params = {key: value.get("wt", "") for key, value in template.get("params", {}).items()}
            if params.get("name") and params.get("price"):
                self.rows.append(dict(template=template.get("target", {}).get("wt", "").strip(), params=params))


def metres(a_lat, a_lon, b_lat, b_lon):
    lat1, lat2 = math.radians(float(a_lat)), math.radians(float(b_lat))
    dlat, dlon = lat2 - lat1, math.radians(float(b_lon) - float(a_lon))
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, value)))


def extract(directory):
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if run["status"] != "success" or run["supplement_kind"] != "voyage_baoshan":
        raise ValueError("Successful bounded Baoshan acquisition required")
    records = []
    for meta in run["requests"]:
        body = (directory / meta["raw_ref"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise ValueError("Listing raw file changed")
        if meta["raw_ref"] != "baoshan.raw":
            continue
        parser = Listings()
        parser.feed(body.decode("utf-8"))
        for index, row in enumerate(parser.rows, 1):
            row.update(source_url=meta["url"], raw_ref=f"baoshan.raw#priced-template={index}",
                       collected_at=meta["collected_at"], raw_sha256=meta["sha256"],
                       license="CC BY-SA 4.0", attribution="Wikivoyage contributors; see article history",
                       price_policy_id=None, budget_eligible=False,
                       date_meaning="lastedit is listing checking date, not a guaranteed effective price interval")
            records.append(row)
    if not records:
        raise ValueError("No structured priced listings; retain raw HTML for review")
    dump_lines(directory / "priced-listings.jsonl", records)
    dump_json(directory / "listing-summary.json", dict(priced_listing_observations=len(records),
        checked_2026_count=sum(r["params"].get("lastedit", "").startswith("2026-") for r in records),
        budget_eligible_count=0))
    return records


if __name__ == "__main__":
    records = extract(Path(sys.argv[1]))
    print(json.dumps([r["params"] for r in records if r["params"].get("lastedit", "").startswith("2026-")], ensure_ascii=False))
