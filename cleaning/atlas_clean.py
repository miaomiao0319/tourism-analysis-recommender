"""Clean immutable Atlas exports into contract 1.0 files; no network or database.

Run: python -m cleaning.atlas_clean RAW_DIRECTORY NEW_BATCH_ID
Only explicit publisher IDs link observations. Unknown prices remain unknown.
"""
import csv
import hashlib
import json
import platform
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from crawler.atlas_collect import PROVINCES, read_csv

ROOT = Path(__file__).resolve().parents[1]
FIELDS = "batch_id attraction_id name country_code province_key province_name city_key city_name grade_system grade_status grade_level type_codes price_form price_min price_max currency price_basis price_policy_id price_raw source_refs collected_at".split()
TYPES = {"nature": "自然景观", "heritage": "历史遗产", "culture": "文化", "city": "城市景观"}
KINDS = ("sites", "featured", "5a")


def text(value):
    return value.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:48]


def dump_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def dump_lines(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def build(tables, requests, raw_ref, batch_id):
    """Pure transform; inputs stay unchanged. Return rows and all audit evidence."""
    entities, evidence, excluded = {}, [], []
    atlas_names = defaultdict(set)
    for kind in ("sites", "featured"):
        for raw in tables[kind]:
            atlas_names[(raw["id"], raw["region_id"])].add(text(raw["name_zh"]))
    issues = defaultdict(set)
    for kind in KINDS:
        for index, raw in enumerate(tables[kind], 2):
            ref = f"e_{kind}_{index}"
            sid = raw.get("mct_id", "") if kind == "5a" else raw.get("id", "")
            source_id = raw.get("atlas_id", "") if kind == "5a" else sid
            identity = "atlas:" + source_id
            if kind == "5a" and text(raw.get("name_zh", "")) not in atlas_names.get((source_id, raw["region_id"]), set()):
                identity = "atlas5a:" + sid
            checked = raw.get("verified") or None
            ev = {"source_ref": ref, "source_id": "atlas_" + kind, "source_item_id": sid or None,
                  "source_url": requests[kind]["url"], "collected_at": requests[kind]["collected_at"],
                  "source_date": None, "source_date_kind": "unknown",
                  "publisher_checked_date": checked,
                  "raw_ref": f"{raw_ref}/{kind}.raw#csv-record={index}", "raw": dict(raw)}
            evidence.append(ev)
            code, name = raw.get("region_id", ""), text(raw.get("name_zh", ""))
            reason = None
            if code not in PROVINCES:
                reason = "outside_31_region_scope" if code in ("710000", "810000", "820000") else "unresolved_region"
            elif not sid or (kind != "5a" and not source_id):
                reason = "missing_source_identity"
            elif not name or len(name) > 512 or any(ord(c) < 32 for c in name):
                reason = "invalid_name"
            if reason:
                excluded.append({"source_ref": ref, "reason": reason})
                continue
            aid = "atl_" + digest(identity)
            entity = entities.setdefault(aid, {"identity": identity, "code": code, "observations": []})
            if entity["code"] != code:
                raise ValueError("Explicit publisher identity has conflicting provinces; review before merging")
            entity["observations"].append({"kind": kind, "ref": ref, "raw": raw, "name": name})

    # A linked destination can be broader than a rated scenic area: not an identity proof.
    linked_groups = []
    crosswalk = defaultdict(lambda: defaultdict(set))
    for aid, entity in entities.items():
        for observation in entity["observations"]:
            if observation["kind"] != "5a" or not observation["raw"].get("atlas_id"):
                continue
            target_id = "atl_" + digest("atlas:" + observation["raw"]["atlas_id"])
            target = entities.get(target_id)
            if target is None:
                continue
            if target["code"] != entity["code"]:
                raise ValueError("Publisher link has conflicting provinces")
            if aid != target_id:
                linked_groups.append(sorted([aid, target_id]))
            prefecture = text(observation["raw"].get("prefecture", ""))
            if prefecture:
                for linked in target["observations"]:
                    city = text(linked["raw"].get("city", ""))
                    if city:
                        crosswalk[(entity["code"], city)][prefecture].add(observation["ref"])

    ev_by_ref = {row["source_ref"]: row for row in evidence}
    regions = {"CN:" + code: {"key": "CN:" + code, "name": name, "country_code": "CN",
                              "level": "province", "parent_key": None}
               for code, name in PROVINCES.items()}
    output, identity_map = [], []
    name_groups = defaultdict(list)
    for aid, entity in sorted(entities.items()):
        code, observations = entity["code"], entity["observations"]
        refs = sorted(o["ref"] for o in observations)
        names = {o["name"] for o in observations}
        if len(names) > 1:
            issues[aid].add("name_aliases_preserved")
        grades, type_codes, type_refs, city_candidates = set(), set(), [], defaultdict(set)
        raw_cities = set()
        for o in observations:
            raw = o["raw"]
            if o["kind"] == "5a":
                grades.add("5A")
                if text(raw.get("prefecture", "")):
                    city_candidates[text(raw["prefecture"])].add(o["ref"])
            else:
                grades.update(token.strip() for token in raw["designations"].split(";")
                              if re.fullmatch("[1-5]A", token.strip()))
                category = raw.get("category", "")
                if category in TYPES:
                    type_codes.add("atlas_" + category)
                    type_refs.append(o["ref"])
                else:
                    issues[aid].add("unknown_source_category")
                original_city = text(raw.get("city", ""))
                if original_city:
                    raw_cities.add(original_city)
                    mapping = crosswalk.get((code, original_city), {})
                    for city, supporting in mapping.items():
                        city_candidates[city].update(supporting)
        # Municipalities are both provincial and city-level units; no capital guessing.
        if code in ("110000", "120000", "310000", "500000"):
            city_candidates = {PROVINCES[code] + "市": set(refs)}
        city_key = city_name = ""
        city_refs = set()
        if len(city_candidates) == 1:
            city_name, city_refs = next(iter(city_candidates.items()))
            city_key = "CN:" + code + ":" + digest(city_name)
            item = regions.setdefault(city_key, {"key": city_key, "name": city_name, "country_code": "CN",
                    "level": "city", "parent_key": "CN:" + code,
                    "basis": "Publisher place/prefecture associations and unique province/original-city crosswalk; geographic rule, not identity merging or an official division-code registry",
                    "source_refs": []})
            item["source_refs"] = sorted(set(item["source_refs"]) | city_refs)
        else:
            issues[aid].add("city_conflict" if city_candidates else "city_unresolved")
        if len(grades) > 1:
            status, system, level = "conflict", "UNKNOWN", ""
            issues[aid].add("grade_conflict")
        elif grades:
            status, system, level = "rated", "CN_A", next(iter(grades))
        else:
            status, system, level = "unknown", "UNKNOWN", ""
        if not grades and any(o["raw"].get("designations") == "national" for o in observations):
            issues[aid].add("heritage_only_not_confirmed_open_attraction")
        source_refs = {"name": refs, "location": sorted(set(refs) | city_refs), "grade": refs}
        if type_refs:
            source_refs["types"] = sorted(type_refs)
        collected = max(ev_by_ref[ref]["collected_at"] for values in source_refs.values() for ref in values)
        row = dict.fromkeys(FIELDS, "")
        row.update(batch_id=batch_id, attraction_id=aid, name=observations[0]["name"], country_code="CN",
                   province_key="CN:" + code, province_name=PROVINCES[code], city_key=city_key, city_name=city_name,
                   grade_system=system, grade_status=status, grade_level=level,
                   type_codes=sorted(type_codes), price_form="unknown", source_refs=source_refs, collected_at=collected)
        output.append(row)
        identity_map.append({"attraction_id": aid, "publisher_identity": entity["identity"],
                             "source_refs": refs, "name_aliases": sorted(names), "original_city_labels": sorted(raw_cities),
                             "merge_basis": "Atlas item ID; 5A joins only with explicit link + same province + identical normalized Chinese name; otherwise isolated mct_id"})
        name_groups[(code, city_key or tuple(sorted(raw_cities)), row["name"])].append(aid)
    suspected = [list(ids) for ids in sorted({tuple(group) for group in linked_groups})]
    suspected += [ids for ids in name_groups.values() if len(ids) > 1]
    for group in suspected:
        for aid in group:
            issues[aid].add("possible_related_or_duplicate_entity_not_merged")
    dictionaries = {"regions": list(regions.values()), "types": [
        {"code": "atlas_" + code, "label": label, "definition": "Publisher category: " + code,
         "method": "source", "basis": "Atlas sites/featured category; retains publisher meaning"}
        for code, label in TYPES.items()],
        "grade_systems": [{"code": "UNKNOWN", "label": "未知体系", "levels": [], "basis": "Contract 1.0"},
                          {"code": "CN_A", "label": "中国A级景区", "levels": ["1A", "2A", "3A", "4A", "5A"],
                           "basis": "Publisher designations/5A export, not independently verified official grades"}],
        "price_policies": []}
    return output, evidence, excluded, identity_map, dictionaries, issues, suspected


def validate(rows, evidence, dictionaries, manifest):
    """Reject inconsistent snapshots rather than emitting usable-looking output."""
    ev = {r["source_ref"] for r in evidence}
    regions = {r["key"]: r for r in dictionaries["regions"]}
    types = {r["code"] for r in dictionaries["types"]}
    ids = set()
    for row in rows:
        aid = row["attraction_id"]
        if aid in ids or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", aid):
            raise ValueError("Duplicate/invalid attraction identity")
        ids.add(aid)
        if list(row) != FIELDS or not row["name"] or row["country_code"] != "CN":
            raise ValueError("Invalid standard fields/name/country")
        for value in row.values():
            if isinstance(value, str) and any(c in value for c in "\r\n\t"):
                raise ValueError("Multiline standard cell")
        for prefix in ("province", "city"):
            key, name = row[prefix + "_key"], row[prefix + "_name"]
            if bool(key) != bool(name) or (key and (key not in regions or regions[key]["name"] != name)):
                raise ValueError("Unresolved region reference")
        if row["city_key"] and regions[row["city_key"]]["parent_key"] != row["province_key"]:
            raise ValueError("City province mismatch")
        if set(row["type_codes"]) - types:
            raise ValueError("Unresolved type reference")
        if row["grade_status"] == "rated":
            if row["grade_system"] != "CN_A" or row["grade_level"] not in ("1A", "2A", "3A", "4A", "5A"):
                raise ValueError("Invalid rated grade")
        elif row["grade_status"] not in ("unknown", "conflict") or row["grade_level"] or row["grade_system"] != "UNKNOWN":
            raise ValueError("Invalid unknown/conflicting grade")
        if row["price_form"] != "unknown" or any(row[f] for f in ("price_min", "price_max", "currency", "price_basis", "price_policy_id", "price_raw")):
            raise ValueError("This source cannot justify a price")
        refs = row["source_refs"]
        if not {"name", "location"} <= refs.keys() or set(refs) - {"name", "location", "grade", "types", "price"}:
            raise ValueError("Invalid source reference groups")
        if any(not values or set(values) - ev for values in refs.values()):
            raise ValueError("Unresolved evidence reference")
    if len(ev) != len(evidence) or not rows:
        raise ValueError("Empty output or duplicate evidence references")
    if manifest["raw_count"] != manifest["excluded_count"] + manifest["accepted_source_count"]:
        raise ValueError("Raw observation counts do not reconcile")
    if manifest["standard_count"] != len(rows) or len(rows) != manifest["accepted_source_count"] - manifest["merged_extra_count"]:
        raise ValueError("Entity counts do not reconcile")


def clean(raw_dir, batch_id, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
        raise ValueError("Invalid batch ID")
    root, raw_dir = root.resolve(), raw_dir.resolve()
    raw_ref = raw_dir.relative_to(root).as_posix()
    run = json.loads((raw_dir / "run.json").read_text(encoding="utf-8"))
    if run["status"] != "success" or run["data_kind"] not in ("real", "test"):
        raise ValueError("Input acquisition is not successful real/test data")
    for request in run["requests"]:
        path = (raw_dir / request["raw_ref"]).resolve()
        if not path.is_relative_to(raw_dir) or hashlib.sha256(path.read_bytes()).hexdigest() != request["sha256"]:
            raise ValueError("Raw file hash mismatch or unsafe path")
    requests, tables = {}, {}
    for kind in KINDS:
        requests[kind] = next(r for r in run["requests"] if r["raw_ref"] == kind + ".raw")
        requests[kind] = dict(requests[kind], collected_at=datetime.fromisoformat(requests[kind]["collected_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
        required = ["mct_id", "atlas_id", "prefecture"] if kind == "5a" else ["id", "city", "category", "designations"]
        tables[kind] = read_csv((raw_dir / (kind + ".raw")).read_bytes(), required + ["region_id", "name_zh"])
        if len(tables[kind]) != run["files"][kind]["row_count"]:
            raise ValueError("Acquisition CSV row counts changed")
    processed, metadata = root / "data/processed" / batch_id, root / "data/metadata" / batch_id
    if processed.exists() or metadata.exists():
        raise FileExistsError("Batch already exists; choose a new batch ID")
    metadata.mkdir(parents=True)
    status = {"status": "in_progress", "batch_id": batch_id, "python": platform.python_version(),
              "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "tool": "Python standard library; unified WSL/Python3.11 environment not verified"}
    try:
        rows, evidence, excluded, identity_map, dictionaries, issues, suspected = build(tables, requests, raw_ref, batch_id)
        count = sum(len(v) for v in tables.values())
        quality = {"missing_city_count": sum(not r["city_key"] for r in rows),
                   "unknown_grade_count": sum(r["grade_status"] == "unknown" for r in rows),
                   "conflicting_grade_count": sum(r["grade_status"] == "conflict" for r in rows),
                   "missing_type_count": sum(not r["type_codes"] for r in rows),
                   "unknown_price_count": len(rows), "conflicting_price_count": 0,
                   "covered_province_count": len({r["province_key"] for r in rows}),
                   "distinct_city_dictionary_entries_used": len({r["city_key"] for r in rows if r["city_key"]}),
                   "province_counts": dict(sorted(Counter(r["province_name"] for r in rows).items())),
                   "grade_status_counts": dict(Counter(r["grade_status"] for r in rows)),
                   "exclusion_reasons": dict(Counter(r["reason"] for r in excluded)),
                   "issue_counts": dict(Counter(issue for values in issues.values() for issue in values)),
                   "suspected_duplicate_groups": suspected,
                   "map_unmatched_count": len(rows),
                   "notes": ["Secondary source grades; no independent official verification", "Publisher checked dates are not historical validity dates", "Heritage-only sites remain candidates with opening status unverified", "No price or budget eligibility; no approved price policy", "5A links merge only with same province and identical normalized Chinese name; broader destinations remain separate linked candidates", "Unmapped cities are blank; dictionary prefecture labels may be abbreviated", "City crosswalk derives geographic associations; it does not assert attraction identity or official administrative codes"]}
        manifest = {"contract_version": "1.0", "batch_id": batch_id, "data_kind": run["data_kind"],
                    "data_cutoff_month": "2026-10", "created_at": status["started_at"],
                    "raw_count": count, "excluded_count": len(excluded), "accepted_source_count": count - len(excluded),
                    "merged_extra_count": count - len(excluded) - len(rows), "standard_count": len(rows),
                    "raw_inputs": [{"path": raw_ref + "/" + r["raw_ref"], "sha256": r["sha256"]}
                                   for r in run["requests"]], "quality": quality,
                    "input_roles": {"sites": "attraction observations", "featured": "attraction observations", "5a": "attraction observations", "regions": "acquired reference, not attraction observations"}}
        validate(rows, evidence, dictionaries, manifest)
        if quality["covered_province_count"] != 31 and run["data_kind"] == "real":
            raise ValueError("Real nationwide batch lost target province coverage")
        processed.mkdir(parents=True)
        standard = processed / "attractions.csv"
        with standard.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
        dump_json(metadata / "dictionaries.json", dictionaries)
        dump_lines(metadata / "evidence.jsonl", evidence)
        dump_lines(metadata / "excluded.jsonl", excluded)
        dump_lines(metadata / "entity-map.jsonl", identity_map)
        dump_lines(metadata / "quality-records.jsonl", ({"attraction_id": aid, "issues": sorted(values)} for aid, values in sorted(issues.items())))
        dump_lines(metadata / "sources.jsonl", ({"source_id": "atlas_" + kind, "name": "Atlas of China / " + kind,
            "base_url": requests[kind]["url"], "coverage": "Mainland 31 regions; other regions excluded with reasons",
            "collection_basis": "Explicit CSV exports, robots Allow /; CC BY 4.0 at https://www.atlasofchina.com/data/",
            "redistribution_status": "allowed", "license": "CC BY 4.0",
            "attribution": "Atlas of China — https://www.atlasofchina.com/data/",
            "notes": "Attribution required; fields changed by documented cleaning; secondary publisher, not official certification"} for kind in KINDS))
        manifest.update(standard_file=standard.relative_to(root).as_posix(),
                        standard_sha256=hashlib.sha256(standard.read_bytes()).hexdigest(),
                        dictionaries_sha256=hashlib.sha256((metadata / "dictionaries.json").read_bytes()).hexdigest())
        # Read back the written exchange format to catch serialization errors.
        parsed = read_csv(standard.read_bytes(), FIELDS)
        for row in parsed:
            row["type_codes"], row["source_refs"] = json.loads(row["type_codes"]), json.loads(row["source_refs"])
        validate(parsed, evidence, dictionaries, manifest)
        province_table = "\n".join(f"| {name} | {n} |" for name, n in quality["province_counts"].items())
        report = f"""# 首轮清洗结果：{batch_id}

这是标准化候选记录批次，不是已完全消除疑似重复、核实开放状态和价格的全国景点全集。

## 数量对账

| 项目 | 数量 |
| --- | ---: |
| 输入来源观察（sites + featured + 5a） | {count} |
| 排除观察 | {len(excluded)} |
| 接受观察 | {manifest['accepted_source_count']} |
| 同实体合并的额外观察 | {manifest['merged_extra_count']} |
| 标准化候选记录 | {len(rows)} |

对账：输入=排除+接受；输出=接受−合并额外观察。地区元数据、网页请求数不计入景点观察数。香港、澳门记录仅在本次31地区分析范围外排除，原始文件仍保留。

## 实际处理

1. 校验采集正文摘要；原始文件未改写。
2. 名称去首尾空白，换行和制表符替换为空格；保留有效标点。省份按原始地区代码对应。
3. 原始城市名按省份区分。利用来源关联的中文地级名称建立字典，仅采用唯一对应；有歧义或无法确认时留空，原文在evidence中保留。该字典仍需补充核实，不是官方区划代码表。
4. 同来源条目标识保持实体稳定；5A名录只有关联标识、省份、规范化中文名均一致时才合并。景区与内部景点、不同地点同名景点分别保留。来源链接但名称不同的记录只标记待核实关系。
5. 来源类别保留为4类来源分类。单一A级标签按来源登记；多等级标记冲突，未提供等级记未知；文保身份不转成A级。
6. 本来源无票价：price_form=unknown，金额、币种和比较政策留空，不参与保证满足预算的推荐。
7. 按契约21列表头输出UTF-8/LF CSV，回读校验字段、字典、来源引用、主键及数量关系。

## 尚待处理

- 覆盖{quality['covered_province_count']}个省级地区；使用{quality['distinct_city_dictionary_entries_used']}个城市/地级地区字典项，城市未知{quality['missing_city_count']}条。
- 等级未知{quality['unknown_grade_count']}条、冲突{quality['conflicting_grade_count']}条；这些是二次来源标签，尚未逐条官方核验。
- 类型未知{quality['missing_type_count']}条；价格未知{len(rows)}条。
- 疑似重复或范围相关关系{len(suspected)}组，均未强行合并。文保点和组合旅行地点的旅游开放范围未验证。
- 来源核查日期不等于各字段在2026-10时点的历史有效性证明。

## 产物怎么读

- attractions.csv：在data/processed同批次目录中，是统一字段的候选快照。
- manifest.json：输入摘要、输出摘要、数量对账和质量统计。
- evidence.jsonl：原始记录、URL、采集时间及逻辑CSV行定位。
- excluded.jsonl：每条排除记录及原因；entity-map.jsonl：来源观察与实体标识的对应关系。
- dictionaries.json：地区、类型和等级字典；quality-records.jsonl：逐实体问题清单。

| 省级地区 | 标准化候选记录 |
| --- | ---: |
{province_table}

下一步计划：核实来源关联与景区包含关系、补充城市字典及明确开放许可的门票来源。MySQL/HDFS尚未导入，Python3.11/WSL统一环境尚未验证。
"""
        (metadata / "清洗结果说明.md").write_text(report, encoding="utf-8", newline="\n")
        dump_json(metadata / "manifest.json", manifest)
        status["status"] = "success"
        return manifest
    except Exception as exc:
        status.update(status="failed", error=str(exc))
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        dump_json(metadata / "run.json", status)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m cleaning.atlas_clean RAW_DIRECTORY NEW_BATCH_ID")
    result = clean(Path(sys.argv[1]), sys.argv[2])
    print(json.dumps({key: result[key] for key in ("batch_id", "raw_count", "excluded_count", "merged_extra_count", "standard_count")}, ensure_ascii=True))
