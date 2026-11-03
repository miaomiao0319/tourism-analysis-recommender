"""Retain named Wikivoyage fee sections and listing parameters with provenance."""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
import sys

from cleaning.atlas_clean import dump_json, dump_lines


class Sections(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections, self.heading, self.current, self.skip = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "h2":
            self.heading = []
        if tag in ("p", "li", "tr", "h3") and self.current:
            self.current["parts"].append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.heading is not None:
            self.heading.append(data)
        elif self.current is not None:
            self.current["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "h2" and self.heading is not None:
            self.current = dict(heading="".join(self.heading).strip(), parts=[])
            self.sections.append(self.current)
            self.heading = None


def fee_sections(body):
    parser = Sections()
    parser.feed(body.decode("utf-8"))
    return [dict(heading=r["heading"], text=re.sub(r"[ \t]+", " ", "".join(r["parts"])).strip())
            for r in parser.sections if r["heading"].lower() in ("fees and permits", "fees", "fees/permits")]


def extract(directory):
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if run["status"] != "success" or run["supplement_kind"] != "voyage_prices":
        raise ValueError("Successful licensed voyage acquisition required")
    results = []
    for meta in run["requests"]:
        body = (directory / meta["raw_ref"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise ValueError("Voyage raw file changed")
        if meta["raw_ref"] in ("robots.raw", "license.raw"):
            continue
        revision = re.search(r'oldid=(\d+)', body.decode("utf-8"))
        for section in fee_sections(body):
            results.append(dict(section, source_url=meta["url"], raw_ref=meta["raw_ref"],
                collected_at=meta["collected_at"], revision_id=revision.group(1) if revision else None,
                license="CC BY-SA 4.0", attribution="Wikivoyage contributors; article history and license retained",
                historical_validity_confirmed=False, price_policy_id=None, budget_eligible=False))
    dump_lines(directory / "fee-sections.jsonl", results)
    dump_json(directory / "fee-summary.json", dict(section_count=len(results), budget_eligible_count=0,
        notes="Fee sections are evidence candidates; page revision date does not establish the effective date of each quoted price"))
    return results


if __name__ == "__main__":
    result = extract(Path(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
