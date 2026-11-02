"""Reviewed seasonal admission evidence; keep caps separate from actual quotes."""
import copy
import csv
import json
from datetime import datetime, timezone

from cleaning.atlas_clean import ROOT, FIELDS, dump_json, dump_lines, validate
from cleaning.admission_pilot import POLICY, load_rows, read_lines, sha, money, validate_price

PARENT = "atlas_clean_20261102_01"
BATCH = "atlas_clean_20261102_02"
PHOENIX = "atl_a05c72cb9284e6b5df743ca21dd06bb8adb9b4ade6486f4f"
URL = "https://fgw.chaoyang.gov.cn/html/CYFGW/202512/0176783480557782.html"
LOC = "https://chaoyang.gov.cn/html/CYSZF/202105/1162105154524963.html"


def phoenix_quote(text):
    for token in (URL, "旺季价格为60元", "淡季价格为30元", "4月1日至10月31日", "2027年12月31日", "2025-12-10"):
        if token not in text:
            raise ValueError("Seasonal price evidence incomplete")
    if "最高限价" in text:
        raise ValueError("Ceiling is not an actual exact quote")
    return "60.00"


def expanded_price(row, evidence, dictionaries):
    if row["attraction_id"] != PHOENIX:
        return validate_price(row, evidence, dictionaries)
    policy = [p for p in dictionaries["price_policies"] if p["id"] == POLICY and p.get("approval_ref") and p["currency"] == "CNY"]
    if not policy or row["price_form"] != "exact" or row["price_policy_id"] != POLICY or row["currency"] != "CNY" or row["price_min"] != "60.00" or row["price_max"] != "60.00":
        raise ValueError("Invalid seasonal qualification")
    ev = [e for e in evidence if e["source_ref"] in row["source_refs"].get("price", [])]
    if len(ev) != 1 or ev[0].get("source_url") != URL or ev[0].get("season") != "04-01/10-31" or ev[0].get("effective_to") != "2027-12-31":
        raise ValueError("Seasonal source reference missing")


def main(root=ROOT):
    old = root / "data/metadata" / PARENT
    manifest = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["raw_inputs"]:
        if sha(root / item["path"]) != item["sha256"]:
            raise ValueError("Parent input hash mismatch")
    standard = root / manifest["standard_file"]
    if sha(standard) != manifest["standard_sha256"] or sha(old / "dictionaries.json") != manifest["dictionaries_sha256"]:
        raise ValueError("Parent snapshot hash mismatch")
    rows = load_rows(standard)
    evidence = read_lines(old / "evidence.jsonl")
    sources = read_lines(old / "sources.jsonl")
    dictionaries = json.loads((old / "dictionaries.json").read_text(encoding="utf-8"))
    validate(rows, evidence, dictionaries, manifest, validate_price)
    capture_path = root / "data/raw/admission_followup_20261102_01/web-responses.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    responses = capture["responses"]
    amount = phoenix_quote(responses[1])
    if "位于辽宁省朝阳市区东部" not in responses[-1]:
        raise ValueError("Actual location proof missing")
    timestamp = datetime.strptime(capture["collected_at"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    previous = copy.deepcopy(rows)
    target = next(r for r in rows if r["attraction_id"] == PHOENIX)
    if (target["name"], target["province_name"], target["city_name"]) != ("朝阳凤凰山", "辽宁", "朝阳市"):
        raise ValueError("Entity locality mismatch; do not match another Phoenix Mountain")
    for kind, url, date, index in (("price", URL, "2025-12-10", 1), ("location", LOC, "2025-08-06", len(responses)-1)):
        evidence.append(dict(source_ref="e_phoenix_"+kind, source_id="chaoyang_"+kind, source_item_id=None,
            source_url=url, collected_at=timestamp, source_date=date, source_date_kind="published",
            raw_ref=capture_path.relative_to(root).as_posix()+"#responses="+str(index),
            effective_from="2025-12-10", effective_to="2027-12-31", season="04-01/10-31"))
        sources.append(dict(source_id="chaoyang_"+kind, name="朝阳市政府/发改委定向核验", base_url=url,
            coverage="辽宁朝阳凤凰山", collection_basis="网页工具读取行政定价及所在地事实",
            redistribution_status="unknown", notes="非整站开放许可；不转载照片和介绍全文"))
    target.update(price_form="exact", price_min=amount, price_max=amount, currency="CNY", price_policy_id=POLICY,
        price_basis="普通全价旺季基础入园票；每年4月1日至10月31日，不含观光车",
        price_raw="旺季门票60元/人次；淡季30元；观光车单程10元另计", collected_at=max(timestamp,target["collected_at"]))
    target["source_refs"]["price"] = ["e_phoenix_price"]
    target["source_refs"]["location"].append("e_phoenix_location")
    for row in rows:
        row["batch_id"] = BATCH
    manifest.update(batch_id=BATCH, parent_batch_id=PARENT, created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    for key in ("raw_count", "accepted_source_count", "merged_extra_count"):
        manifest[key] += 2
    manifest["quality"]["unknown_price_count"] -= 1
    manifest["quality"]["comparable_price_count"] = 2
    manifest["quality"]["notes"] = [s for s in manifest["quality"]["notes"] if not s.startswith("One approved Guimeng")]
    manifest["quality"]["notes"].append("Two qualified base admission quotes; seasonal Phoenix price applies throughout October, caps kept outside standard prices")
    for path in [standard, capture_path, *(old / n for n in ("manifest.json", "dictionaries.json", "evidence.jsonl", "sources.jsonl", "entity-map.jsonl"))]:
        manifest["raw_inputs"].append(dict(path=path.relative_to(root).as_posix(), sha256=sha(path)))
    validate(rows, evidence, dictionaries, manifest, expanded_price)
    changed = [a["attraction_id"] for a,b in zip(previous,rows) if any(a[f]!=b[f] for f in FIELDS if f!="batch_id")]
    if changed != [PHOENIX] or not money(amount) > money("59.99") or not money(amount) <= money("60.00"):
        raise ValueError("Unexpected snapshot changes or budget boundary")
    output = root / "data/metadata" / BATCH
    processed = root / "data/processed" / BATCH
    if output.exists() or processed.exists():
        raise FileExistsError("Immutable batch exists")
    output.mkdir(); processed.mkdir()
    target_path = processed / "attractions.csv"
    with target_path.open("x", encoding="utf-8", newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator="\n"); writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if k in ("type_codes","source_refs") else v for k,v in row.items()})
    dump_json(output / "dictionaries.json", dictionaries)
    dump_lines(output / "sources.jsonl", sources); dump_lines(output / "evidence.jsonl", evidence)
    dump_lines(output / "entity-map.jsonl", read_lines(old / "entity-map.jsonl"))
    manifest.update(standard_file=target_path.relative_to(root).as_posix(),standard_sha256=sha(target_path),dictionaries_sha256=sha(output / "dictionaries.json"))
    validate(load_rows(target_path), evidence, dictionaries, manifest, expanded_price)
    dump_json(output / "manifest.json", manifest)
    dump_json(output / "followup-validation.json", dict(status="success", changed_entities=changed, comparable_prices=2,
        budget_59_99=False,budget_60=True, standard_count=len(rows), database_integrated=False,
        retained_candidates=[dict(name="沂蒙山云蒙景区",amount="70.00",status="subarea_entity_registration_pending"),
        dict(name="天上王城",amount="80.00",status="ceiling_not_actual_quote"),dict(name="雪山彩虹谷",amount="80.00",status="ceiling_not_actual_quote"),
        dict(name="沂蒙山根据地",amount="50.00",status="ceiling_not_actual_quote")],
        failed_fulltext_urls=["https://www.yishui.gov.cn/info/18926/393575.htm","https://www.yishui.gov.cn/info/18926/385759.htm"]))
    print(json.dumps(dict(batch=BATCH,standard_count=len(rows),comparable_prices=2)))


if __name__ == "__main__":
    main()
