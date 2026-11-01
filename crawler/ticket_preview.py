"""Extract original ticket-table cells; do not infer prices or attraction identity."""
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

from cleaning.atlas_clean import dump_lines, dump_json


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.heading, self.current_heading = [], None, ""
        self.table, self.cell, self.row = None, None, []

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3"):
            self.heading = []
        if tag == "table":
            self.table = {"heading": self.current_heading, "rows": []}
        if self.table is not None and tag == "tr":
            self.row = []
        if self.table is not None and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("h2", "h3") and self.heading is not None:
            self.current_heading, self.heading = "".join(self.heading), None
        if tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        if tag == "tr" and self.table is not None and self.row:
            self.table["rows"].append(self.row)
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def parse(body):
    parser = Tables()
    parser.feed(body.decode("utf-8"))
    result = []
    for table_index, table in enumerate(parser.tables, 1):
        if not table["rows"]:
            continue
        headers = table["rows"][0]
        price_columns = [i for i, value in enumerate(headers) if value.strip() in ("门票(元)", "门票参考(元)")]
        if len(price_columns) != 1 or len(headers) < 2:
            continue
        for row_index, cells in enumerate(table["rows"][1:], 2):
            if len(cells) != len(headers):
                raise ValueError("Malformed ticket table: keep raw file for review")
            result.append(dict(table_index=table_index, row_index=row_index,
                               heading_raw=table["heading"], headers_raw=headers,
                               cells_raw=cells, name_raw=cells[0], price_raw=cells[price_columns[0]]))
    return result


def preview(directory):
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if run["status"] != "success" or run["supplement_kind"] != "prices":
        raise ValueError("Successful price supplement required")
    records = []
    for meta in run["requests"]:
        body = (directory / meta["raw_ref"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise ValueError("Raw file changed")
        if meta["raw_ref"] not in ("costs.raw", "destinations.raw"):
            continue
        for item in parse(body):
            item.update(source_url=meta["url"], collected_at=meta["collected_at"],
                        raw_ref=f"{meta['raw_ref']}#table={item['table_index']}/row={item['row_index']}",
                        source_date=None, source_date_kind="unknown", license="CC BY 4.0",
                        attribution="张家口旅游数据百科 / https://data.zjktravel.com/",
                        attraction_id=None, price_policy_id=None, budget_eligible=False,
                        status="raw_reference_only_not_historical_or_entity_verified")
            records.append(item)
    if not records:
        raise ValueError("No ticket tables found")
    dump_lines(directory / "ticket-observations-v2.jsonl", records)
    dump_json(directory / "ticket-summary-v2.json", dict(observation_count=len(records),
        distinct_name_strings=len({r["name_raw"] for r in records}),
        normalized_price_count=0, linked_attraction_count=0, budget_eligible_count=0,
        warning="Travel-agency reference prices; scope, ticket basis and historical validity unresolved; do not copy into the standard snapshot"))
    return len(records)


if __name__ == "__main__":
    print(preview(Path(sys.argv[1])))
