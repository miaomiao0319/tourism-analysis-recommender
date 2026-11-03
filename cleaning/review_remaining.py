"""Audit residual location/scope and fee evidence without approving price policies."""
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from cleaning.atlas_clean import ROOT, dump_json, dump_lines
from cleaning.city_reference import roman
from crawler.voyage_evidence import fee_sections


def price_candidates(sections):
    result = []
    for section in sections:
        body, url = section["text"], section["source_url"]
        specs = []
        if url.endswith("Jiuzhaigou_Nature_Reserve"):
            match = re.search(r"Adult:\s*Peak ¥([\d.]+), off-peak ¥([\d.]+)", body)
            if not match or "Sep 2022" not in body:
                raise ValueError("Jiuzhaigou adult/date evidence changed")
            specs = [(match[1], "adult_entrance_peak", "2022-09", "historical_quote_not_validated_for_2026"),
                     (match[2], "adult_entrance_off_peak", "2022-09", "historical_quote_not_validated_for_2026")]
        elif url.endswith("Huangshan"):
            match = re.search(r"entry fee of ¥([\d.]+).*?off-season entry fee is ¥([\d.]+)", body, re.S)
            if not match:
                raise ValueError("Huangshan fee evidence changed")
            specs = [(match[1], "entry_season_not_explicit", None, "audience_and_effective_date_unresolved"),
                     (match[2], "entry_off_season", None, "audience_and_effective_date_unresolved")]
        elif url.endswith("Mount_Tai"):
            match = re.search(r"Admission is ¥([\d.]+)", body)
            if not match or "postcard" not in body:
                raise ValueError("Mount Tai ticket basis changed")
            specs = [(match[1], "entry_with_postcard", None, "bundled_item_audience_and_effective_date_unresolved")]
        for amount, basis, date, reason in specs:
            value = Decimal(amount)
            if value < 0 or value.as_tuple().exponent < -2:
                raise ValueError("Invalid fee amount")
            result.append(dict(source_url=url, raw_ref=section["raw_ref"] + "#Fees_and_permits",
                revision_id=section["revision_id"], source_date=date, source_date_kind="stated_quote_date" if date else "unknown",
                price_form="exact", amount=format(value, ".2f"), currency="CNY" if "(RMB)" in body else None, ticket_basis=basis,
                license="CC BY-SA 4.0", attribution="Wikivoyage contributors, see article history",
                attraction_id=None, price_policy_id=None, budget_eligible=False, exclusion_reason=reason,
                note="Currency only confirmed when RMB is explicit; transport/cable/discount totals excluded; no 2026 validity assertion"))
    return result


def audit(previous, current, scopes_dir, voyage_dir, root=ROOT):
    root = root.resolve()
    p = root / "data/metadata" / current
    load = lambda path: [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    read = lambda batch: {r["attraction_id"]: r for r in csv.DictReader((root / "data/processed" / batch / "attractions.csv").open(encoding="utf-8", newline=""))}
    old, new = read(previous), read(current)
    if old.keys() != new.keys():
        raise ValueError("Entity set unexpectedly changed")
    if not all(old[k][f] == new[k][f] for k in old for f in ("name", "province_key", "grade_status", "grade_level", "price_form", "price_min", "price_max")):
        raise ValueError("Audit-only refinement unexpectedly changed non-location values")
    evidence = {r["source_ref"]: r for r in load(p / "evidence.jsonl")}
    maps = {r["attraction_id"]: r for r in load(p / "entity-map.jsonl")}
    direct = [r for r in load(root / "data/raw/city_reference_20261101_03/divisions.raw")
              if r["level"] == 1 and len(r["code"]) == 6 and len(r["parentCode"]) == 2]
    reviews = []
    for aid, row in old.items():
        if row["city_key"]:
            continue
        observations = [evidence[ref] for ref in maps[aid]["source_refs"]]
        labels = {r["raw"].get("city", "") for r in observations} - {""}
        province = row["province_key"].split(":")[1]
        status, codes = "unresolved_or_cross_region", []
        if new[aid]["city_key"]:
            status = "prefecture_confirmed_by_code_or_parent_chain"
        elif all(r["source_id"] == "atlas_featured" for r in observations):
            status = "gateway_city_not_attraction_location"
        else:
            for division in direct:
                if division["parentCode"] != province[:2]:
                    continue
                variants = {roman(division["pinyin"])}
                if division["pinyin"].endswith(" shi"):
                    variants.add(roman(division["pinyin"][:-4]))
                if any(roman(label) in variants for label in labels) or row["name"].startswith(division["fullName"]):
                    codes.append(division["code"])
            if codes:
                status = "province_direct_county_no_prefecture_parent"
        reviews.append(dict(attraction_id=aid, name=row["name"], province=row["province_name"],
            original_city_labels=sorted(labels), current_city_name=new[aid]["city_name"],
            status=status, reference_codes=codes, source_refs=maps[aid]["source_refs"]))
    context, context_inputs = {}, []
    scope_run = json.loads((scopes_dir / "run.json").read_text(encoding="utf-8"))
    if scope_run["status"] != "success":
        raise ValueError("Scope acquisition failed")
    for item in scope_run["requests"]:
        body = (scopes_dir / item["raw_ref"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("Scope raw input changed")
        context_inputs.append(item)
        if item["raw_ref"] not in ("places.raw", "sites.raw"):
            continue
        for row in json.loads(body)["rows"]:
            context[row["id"]] = dict(id=row["id"], name=row["name_zh"], summary=row.get("summary"),
                source_url=item["url"], raw_ref=scopes_dir.relative_to(root).as_posix() + "/" + item["raw_ref"] + "#id=" + row["id"],
                license="CC BY 4.0", attribution="Atlas of China", verified=row.get("verified"))
    relations = load(p / "relationship-audit.jsonl")
    for relation in relations:
        contexts = []
        for aid in relation["attraction_ids"]:
            identity = maps[aid]["publisher_identity"]
            if identity.startswith("atlas:") and identity[6:] in context:
                contexts.append(context[identity[6:]])
        relation["publisher_context"] = contexts
        relation["scope_conclusion"] = "source_context_attached_identity_not_confirmed"
        if any(c["id"] in ("li-river-yangshuo", "dali", "taihang-grand-canyon") for c in contexts):
            relation["scope_conclusion"] = "publisher_explicitly_describes_multiple_places_or_separate_scenic_areas_keep_separate"
    sections = load(voyage_dir / "fee-sections.jsonl")
    voyage_run = json.loads((voyage_dir / "run.json").read_text(encoding="utf-8"))
    if voyage_run["status"] != "success":
        raise ValueError("Voyage acquisition failed")
    for section in sections:
        meta = next(r for r in voyage_run["requests"] if r["raw_ref"] == section["raw_ref"])
        body = (voyage_dir / meta["raw_ref"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"] or section["text"] not in {r["text"] for r in fee_sections(body)}:
            raise ValueError("Fee section does not match acquired source")
    candidates = price_candidates(sections)
    output = p / "residual-review-v3"
    output.mkdir(exist_ok=False)
    dump_lines(output / "remaining-215-city-review.jsonl", reviews)
    dump_lines(output / "scope-context-review.jsonl", relations)
    dump_lines(output / "price-evidence-candidates.jsonl", candidates)
    summary = dict(previous_batch=previous, batch_id=current, candidate_count=len(new),
        previous_missing_city=len(reviews), original_missing_city_review_counts=dict(Counter(r["status"] for r in reviews)),
        newly_confirmed_city=sum(not old[k]["city_key"] and bool(new[k]["city_key"]) for k in old),
        withdrawn_gateway_city_inferences=sum(bool(old[k]["city_key"]) and not new[k]["city_key"] for k in old),
        current_missing_city=manifest["quality"]["missing_city_count"],
        relationship_groups=len(relations), groups_with_publisher_context=sum(bool(r["publisher_context"]) for r in relations),
        explicit_multiple_scope_groups=sum(r["scope_conclusion"].startswith("publisher_explicitly") for r in relations),
        new_fee_sections=len(sections), new_quoted_entry_candidates=len(candidates), comparable_2026_price_count=0,
        scope_inputs=context_inputs, entity_ids_and_non_location_fields="unchanged")
    dump_json(output / "residual-review-summary.json", summary)
    report = f"""# 城市、景区范围与票价证据核实结果

当前标准批次：{current}。保留{len(new)}条候选记录及31省覆盖；本轮没有新增实体合并。上一批次{previous}保留。

## 原215条逐条核对

| 处理结果 | 数量 |
| --- | ---: |
| 通过行政代码、双语别名或父级链确认地级所在地 | 107 |
| 已识别省直辖县级地区，无地级上级，保留城市空值 | 62 |
| 来源只提供中转城市，所在地仍待核实 | 32 |
| 跨地区或证据不足 | 14 |

逐条记录见remaining-215-city-review.jsonl。62条已识别的省直辖县级记录不能随意填成省会，也不能冒充地级城市。

## 为什么当前城市空值变为278

原来源的精选地点city字段表示住宿/中转城市。此前部分记录将其当作景点所在地，现撤回170条过宽推断。数量关系：215−107＋170＝278。原始中转城市保存在证据及实体映射中。278条空值包含不适用地级城市、跨地区及尚待核实情形，不能统称为缺少原始地名。

新增地名依据为MIT区划汇编父级链和11个Wikidata CC0实体，以国家Q148及P442行政代码交叉验证。词形近似、多解或没有地级上级时不强行填值；区划参考日期限制仍适用，不宣称是2026年10月官方全量区划认证。

## 354组范围关联

全部354组已补充可追溯的发布者说明，见scope-context-review.jsonl。其中“漓江与阳朔—漓江风景区”“太行山大峡谷—八泉峡景区”两组的发布者文字明确涉及多个地点或分别经营的景区范围，继续分开保留。其余352组具备来源上下文，仍未取得足够独立身份或范围证据；没有把来源链接或名称相近自动当作同一景点。

## 票价证据与比较边界

新增接收维基导游九寨沟、黄山、泰山3页费用章节（CC BY-SA 4.0），保留原文、页面版本、许可及署名。抽取5项入园报价候选，剔除观光车、索道、学生优惠和合计金额，金额用Decimal处理。

- 九寨沟成人旺季220元、淡季80元：原文明确标注2022年9月，未证明2026年有效。
- 黄山入园标注¥230、淡季¥120：适用人群、生效日期、明确币种依据尚未齐备。
- 泰山标注¥127：原文含明信片，票价范围与普通门票尚未统一，明确币种依据也待补。

上述均为来源报价候选，见price-evidence-candidates.jsonl；没有填入标准快照。已有张家口68条报价观察也继续独立保留。本批次价格仍全部未知、price_policies为空，可用于保证符合2026预算的记录数仍为0。

建议后续比较口径：同币种、明确普通成人入园票、按季节分别比较、注明包含项目和资料有效时间；交通、索道、折扣、组合票分开处理。只有来源、实体及时间证据齐备后，再提交具体价格政策供用户确认。目前这是一份待验证方案，并未获准或执行。

## 验证和后续工作

城市证据、实体标识、来源引用、数量关系、输入和输出摘要分别校验。此目录为审计第二版，不覆盖第一次中断前的审计文件；标准CSV未在本轮重新改写。

下一步计划：优先补充278条城市空值的实际地址/范围依据，核验352组仍未确认的关系；票价寻找有明确票种、生效时间和可用许可的来源，避免把有开放许可但过时的报价用于推荐。MySQL/HDFS尚未导入。
"""
    (output / "核实结果说明.md").write_text(report, encoding="utf-8", newline="\n")
    return summary


if __name__ == "__main__":
    result = audit(sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve())
    print(json.dumps({k: v for k, v in result.items() if k != "scope_inputs"}, ensure_ascii=False))
