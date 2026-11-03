"""Publish the approved Guimeng admission pilot as a new immutable snapshot.

Run: python -m cleaning.admission_pilot APPROVAL_JSON NEW_BATCH_ID
This is local cleaning/qualification, not a database or recommendation service.
"""
import copy
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from cleaning.atlas_clean import ROOT, FIELDS, digest, dump_json, dump_lines, validate
from cleaning.targeted_followup import GOV_URL, government_quote

BASE = "atlas_clean_20261101_07"
POLICY = "cn_full_admission_202610"
IDENTITY = "gov_cn:shandong:linyi:guimeng_admission_area"
AID = "gov_" + digest(IDENTITY)
LOCATION_URL = "https://www.linyi.gov.cn/info/4748/209638.htm"


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?", value):
        raise ValueError("Expected nonnegative DECIMAL(12,2) string")
    return Decimal(value)


def validate_price(row, evidence, dictionaries):
    fields = ("price_min", "price_max", "currency", "price_basis", "price_policy_id", "price_raw")
    if row["price_form"] == "unknown":
        if any(row[f] for f in fields):
            raise ValueError("Pilot unknown prices must remain empty")
        return
    # shortcut: only the approved exact Guimeng pilot is published here; add a
    # separate source-specific qualification step before publishing other quotes.
    policies = [p for p in dictionaries["price_policies"] if p["id"] == POLICY]
    if len(policies) != 1 or not policies[0].get("approval_ref"):
        raise ValueError("Approved pilot policy missing")
    if (row["attraction_id"] != AID or row["price_form"] != "exact"
            or row["currency"] != "CNY" or row["price_policy_id"] != POLICY
            or money(row["price_min"]) != Decimal("70.00")
            or row["price_max"] != row["price_min"] or not row["price_basis"] or not row["price_raw"]):
        raise ValueError("Outside the approved source-specific pilot")
    refs = row["source_refs"].get("price", [])
    quotes = [e for e in evidence if e["source_ref"] in refs]
    if len(quotes) != 1:
        raise ValueError("One unambiguous pricing observation required")
    q = quotes[0]
    if (q["source_url"] != GOV_URL or q.get("entity_identity") != IDENTITY
            or q.get("amount") != row["price_min"] or q.get("currency") != "CNY"
            or q.get("ticket_scope") != "basic_full_admission"
            or q.get("effective_from", "9999") > "2026-10-01"
            or q.get("effective_to", "0000") < "2026-10-31"):
        raise ValueError("Price scope, currency or validity evidence missing")


def budget_matches(row, budget, currency, evidence, dictionaries):
    limit = money(budget)
    validate_price(row, evidence, dictionaries)
    return bool(row["price_policy_id"] == POLICY and row["currency"] == currency
                and row["price_form"] == "exact" and money(row["price_min"]) <= limit)


def read_lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for field in ("type_codes", "source_refs"):
            row[field] = json.loads(row[field])
    return rows


def publish(approval_path, batch_id, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
        raise ValueError("Invalid batch id")
    approval_path = Path(approval_path).resolve()
    approval_ref = approval_path.relative_to(root.resolve()).as_posix()
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if (approval.get("policy_id") != POLICY or approval.get("status") != "approved"
            or approval.get("user_message") != "开始进行下一步计划吧"
            or not approval.get("proposal_ref") or not approval.get("proposal_sha256")):
        raise ValueError("Traceable user approval required")
    if sha(root / approval["proposal_ref"]) != approval["proposal_sha256"]:
        raise ValueError("Approved proposal hash mismatch")
    old = root / "data/metadata" / BASE
    original = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
    inputs = original["raw_inputs"] + [dict(path=original["standard_file"], sha256=original["standard_sha256"]),
        dict(path=(old / "dictionaries.json").relative_to(root).as_posix(), sha256=original["dictionaries_sha256"])]
    extra = [approval_path, root / approval["proposal_ref"], old / "manifest.json"]
    extra.extend(old / name for name in ("evidence.jsonl", "sources.jsonl", "entity-map.jsonl"))
    captures = [root / "data/raw/guimeng_price_20261102_01/web-response.json",
                root / "data/raw/guimeng_location_20261102_01/web-response.json"]
    extra.extend(captures)
    inputs.extend(dict(path=p.relative_to(root).as_posix(), sha256=sha(p)) for p in extra)
    for item in inputs:
        if sha(root / item["path"]) != item["sha256"]:
            raise ValueError("Input hash mismatch: " + item["path"])
    capture = [json.loads(p.read_text(encoding="utf-8")) for p in captures]
    quote = government_quote(json.dumps(capture[0]["response"], ensure_ascii=False))
    location = json.dumps(capture[1]["response"], ensure_ascii=False)
    if any(t not in location for t in (LOCATION_URL, "临沂市平邑", "龟蒙是养生旅游区(平邑)", "2026-07-27")):
        raise ValueError("Explicit subarea location evidence missing")
    evidence = read_lines(old / "evidence.jsonl")
    sources = read_lines(old / "sources.jsonl")
    mapping = read_lines(old / "entity-map.jsonl")
    dictionaries = json.loads((old / "dictionaries.json").read_text(encoding="utf-8"))
    rows = load_rows(root / original["standard_file"])
    validate(rows, evidence, dictionaries, original)
    original_rows = copy.deepcopy(rows)
    times = []
    for index, (kind, url, date) in enumerate((("price", GOV_URL, "2026-09-20"), ("location", LOCATION_URL, "2026-07-27"))):
        timestamp = datetime.strptime(capture[index]["collected_at"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        times.append(timestamp)
        evidence.append(dict(source_ref="e_guimeng_" + kind, source_id="linyi_gov_" + kind,
            source_item_id=url.rsplit("/", 1)[1], source_url=url, collected_at=timestamp,
            source_date=date, source_date_kind="published", raw_ref=captures[index].relative_to(root).as_posix() + "#response",
            entity_identity=IDENTITY, **(dict(amount=quote["amount"], currency="CNY", ticket_scope="basic_full_admission",
            effective_from=quote["effective_from"], effective_to=quote["effective_to"], document_no=quote["document_no"])
            if kind == "price" else dict(county="平邑县", city="临沂市", province="山东"))))
        sources.append(dict(source_id="linyi_gov_" + kind, name="临沂市政府 / " + kind,
            base_url="https://www.linyi.gov.cn/", coverage="龟蒙景区定向事实核验",
            collection_basis="网页工具读取；仅使用名称、所在地、金额、文号、日期等事实；非整站爬取",
            redistribution_status="unknown", notes="不声明整站CC许可；行政定价文件依据与一般介绍页区别保存，不公开转载页面"))
    province = next(r for r in dictionaries["regions"] if r["key"] == "CN:370000")
    city = next(r for r in dictionaries["regions"] if r["level"] == "city" and r["parent_key"] == province["key"] and r["name"] in ("临沂", "临沂市"))
    dictionaries["price_policies"].append(dict(id=POLICY, currency="CNY",
        ticket_basis="普通全价游客基础入园票；不含交通、索道、临展、体验；非优惠或免票资格",
        eligibility_rule="对应具体景区、票种明确、有效期覆盖2026-10全月；仅free/exact同额报价；各来源独立核验",
        approval_ref=approval_ref))
    for row in rows:
        row["batch_id"] = batch_id
    row = dict.fromkeys(FIELDS, "")
    row.update(batch_id=batch_id, attraction_id=AID, name=quote["name"], country_code="CN",
        province_key=province["key"], province_name=province["name"], city_key=city["key"], city_name=city["name"],
        grade_system="UNKNOWN", grade_status="unknown", type_codes=[], price_form="exact",
        price_min="70.00", price_max="70.00", currency="CNY", price_basis=quote["ticket_basis"],
        price_policy_id=POLICY, price_raw="龟蒙景区基础门票70元/人；观光车与索道另计", collected_at=max(times),
        source_refs=dict(name=["e_guimeng_price", "e_guimeng_location"], location=["e_guimeng_location"], price=["e_guimeng_price"]))
    rows.append(row)
    mapping.append(dict(attraction_id=AID, publisher_identity=IDENTITY,
        source_refs=["e_guimeng_price", "e_guimeng_location"], name_aliases=[quote["name"]],
        merge_basis="独立龟蒙子景区；不继承聚合目的地等级、类型或票价"))
    manifest = copy.deepcopy(original)
    manifest.update(batch_id=batch_id, created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        parent_batch_id=BASE, raw_inputs=inputs, raw_count=original["raw_count"] + 2,
        accepted_source_count=original["accepted_source_count"] + 2,
        merged_extra_count=original["merged_extra_count"] + 1, standard_count=len(rows))
    q = manifest["quality"]
    for key in ("unknown_grade_count", "missing_type_count", "map_unmatched_count"):
        q[key] += 1
    q["province_counts"][province["name"]] += 1
    q["grade_status_counts"]["unknown"] += 1
    q["comparable_price_count"] = 1
    q["notes"] = [s for s in q["notes"] if s != "No price or budget eligibility; no approved price policy"]
    q["notes"].append("One approved Guimeng basic-admission pilot; other 8430 prices unknown; no inheritance from aggregate grades")
    manifest["input_roles"]["guimeng"] = "two complementary observations of one distinct subarea"
    validate(rows, evidence, dictionaries, manifest, validate_price)
    source_ids = [s["source_id"] for s in sources]
    if len(source_ids) != len(set(source_ids)) or any(e["source_id"] not in source_ids for e in evidence):
        raise ValueError("Unresolved or duplicate source registration")
    for before, after in zip(original_rows, rows):
        if any(before[f] != after[f] for f in FIELDS if f != "batch_id"):
            raise ValueError("Parent row unexpectedly modified")
    report = dict(budget_69_99=budget_matches(row, "69.99", "CNY", evidence, dictionaries),
        budget_70=budget_matches(row, "70.00", "CNY", evidence, dictionaries),
        budget_zero=budget_matches(row, "0", "CNY", evidence, dictionaries),
        currency_mismatch=budget_matches(row, "70", "USD", evidence, dictionaries))
    if report != dict(budget_69_99=False, budget_70=True, budget_zero=False, currency_mismatch=False):
        raise ValueError("Budget boundary check failed")
    output = root / "data/metadata" / batch_id
    processed = root / "data/processed" / batch_id
    if output.exists() or processed.exists():
        raise FileExistsError("Batch already exists")
    output.mkdir(parents=True)
    processed.mkdir(parents=True)
    standard = processed / "attractions.csv"
    with standard.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for item in rows:
            writer.writerow({f: json.dumps(item[f], ensure_ascii=False) if f in ("type_codes", "source_refs") else item[f] for f in FIELDS})
    dump_json(output / "dictionaries.json", dictionaries)
    for name, values in (("evidence", evidence), ("sources", sources), ("entity-map", mapping)):
        dump_lines(output / (name + ".jsonl"), values)
    manifest.update(standard_file=standard.relative_to(root).as_posix(), standard_sha256=sha(standard),
        dictionaries_sha256=sha(output / "dictionaries.json"))
    validate(load_rows(standard), evidence, dictionaries, manifest, validate_price)
    dump_json(output / "manifest.json", manifest)
    dump_json(output / "pilot-validation.json", dict(status="success", checks=report,
        inherited_records_unchanged=len(original_rows), comparable_prices=1, standard_count=len(rows),
        qualification_only=True, database_or_recommender_integrated=False))
    (output / "试点说明.md").write_text("""# 龟蒙基础入园票试点

本轮按用户对上一轮方案的继续执行指示登记政策；批准原文、所承接方案和摘要见政策approval_ref。
流程：核验输入摘要 → 从官方材料核实独立景区及平邑县/临沂市所在地 → 两条互补观察合为一个实体 → 登记获准政策 → Decimal比较 → CSV回读及来源引用检查。

新批次8431条、31省级地区；原8430条业务字段不变，新增龟蒙一条。278条城市空值未因此减少。龟蒙等级和类型未由聚合景区继承。
目前可比价仅1条：70.00 CNY基础入园票，2026-10全月有效；69.99元不匹配，70元匹配。交通、索道、临展和体验另计，优惠人群不能直接套用普通全价。
上海玻璃馆仍是缺生效区间的参考，未进入本批次标准价格。政府页面仅作事实核验，不声称整站CC开放许可。

下一步计划：按同一条件继续补其他景区的有效票价及所在地/范围证据。此为本地数据资格试点，尚未接入MySQL、HDFS或推荐服务。
""", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    result = publish(Path(sys.argv[1]), sys.argv[2])
    print(json.dumps(dict(batch_id=result["batch_id"], standard_count=result["standard_count"])))
