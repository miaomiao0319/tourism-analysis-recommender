"""Turn reviewed web captures into bounded, non-published evidence candidates."""
import csv
import hashlib
import json
import re
from pathlib import Path

from cleaning.atlas_clean import ROOT, dump_json, dump_lines
from crawler.listing_evidence import metres

GOV_URL = "https://www.linyi.gov.cn/info/3442/496729.htm"
MCT_URL = "https://sjfw.mct.gov.cn/site/dataservice/culdetails?curId=10&id=34948"


def government_quote(text):
    for token in (GOV_URL, "临发改价格", "2026-10-01", "2029-09-30", "沂蒙山龟蒙景区门票70元/人"):
        if token not in text:
            raise ValueError("Government pricing evidence changed or incomplete")
    amount = re.search(r"沂蒙山龟蒙景区门票(\d+)元/人", text)[1]
    return dict(name="沂蒙山龟蒙景区", amount=amount + ".00", currency="CNY",
        ticket_basis="普通全价入园票；不含观光车、索道及其他付费项目", source_url=GOV_URL,
        source_date="2026-09-20", effective_from="2026-10-01", effective_to="2029-09-30",
        document_no="临发改价格〔2026〕248号", attraction_id=None,
        scope_warning="Cannot assign this subarea fee to aggregate 沂蒙山旅游区/沂蒙山景区",
        source_basis="Administrative pricing notice; limited factual fields, no blanket CC license asserted",
        rights_basis_reference="https://www.ncac.gov.cn/xxfb/flfg/flfg_532/202103/t20210309_50530.html",
        price_policy_id=None, budget_eligible=False, status="effective_date_and_scope_ready_policy_and_entity_registration_pending")


def glass_quote(text):
    start = text.find("Shanghai Museum of Glass (上海玻璃博物馆)")
    if start < 0:
        raise ValueError("Named museum listing missing")
    end = text.find("## Do", start)
    listing = text[start:end if end >= 0 else None]
    if "updated Jul 2026" not in listing or "685" not in listing:
        raise ValueError("Museum date/address evidence missing")
    match = re.search(r"¥(\d+) for entry to the main museum building", listing)
    if not match:
        raise ValueError("Main-building fee missing; do not take a combo total")
    return dict(name="上海玻璃博物馆", amount=match[1] + ".00", currency=None,
        currency_note="Yuan symbol in licensed listing; Chinese official adult-fee corroboration kept separately",
        source_url="https://en.wikivoyage.org/wiki/Shanghai/Baoshan", listing_checked_month="2026-07",
        effective_from=None, effective_to=None, address="上海市宝山区长江西路685号",
        ticket_basis="主馆单馆；不含儿童馆、迷宫、艺术馆、临展或体验项目",
        license="CC BY-SA 4.0", attribution="Wikivoyage contributors; article revision 5316172",
        price_policy_id=None, budget_eligible=False, status="dated_reference_effective_interval_and_policy_pending")


def main(root=ROOT):
    batch = "atlas_clean_20261101_07"
    output = root / "data/metadata" / batch / "targeted-followup-01"
    output.mkdir(exist_ok=False)
    captures = [root / "data/raw/baoshan_web_capture_20261101_01/web-response.json",
                root / "data/raw/official_scope_price_20261101_01/web-response.json"]
    ba = json.loads(captures[0].read_text(encoding="utf-8"))["response"]
    gov = json.loads(captures[1].read_text(encoding="utf-8"))["response"]
    glass, guimeng = glass_quote(ba), government_quote(gov)
    # These coordinates are the map link observed by the web tool, not a fetched map.
    glass.update(map_link="https://en.wikivoyage.org/wiki/Special%3AMap/17/31.343784/121.470188/en",
                 coordinate_basis="Web tool resolved the listing's map link; destination fetch failed")
    scope_dir = root / "data/raw/atlas_scope_20261101_01"
    scopes = [r for name in ("places", "sites") for r in json.loads((scope_dir / (name + ".raw")).read_bytes())["rows"]]
    museum = next(r for r in scopes if r["id"] == "shanghai-museum-of-glass")
    distance = metres(museum["lat"], museum["lon"], 31.343784, 121.470188)
    if museum["name_zh"] != glass["name"] or museum["region_id"] != "310000" or distance > 500:
        raise ValueError("Museum entity match needs review")
    mappings = [json.loads(line) for line in (root / "data/metadata" / batch / "entity-map.jsonl").read_text(encoding="utf-8").splitlines()]
    glass["attraction_id"] = next(r["attraction_id"] for r in mappings if r["publisher_identity"] == "atlas:shanghai-museum-of-glass")
    glass["coordinate_distance_m"] = round(distance)
    glass["match_basis"] = "Exact bilingual venue name, same municipality, coordinate link within 500 m"
    if "潍坊市和临沂市" not in gov or "龙岩市境内的永定土楼" not in gov or "漳州市境内的南靖土楼" not in gov:
        raise ValueError("Cross-city source evidence incomplete")
    scopes_review = [dict(name="沂蒙山旅游区", cities=["潍坊市", "临沂市"], source_url=MCT_URL,
        conclusion="aggregate_across_cities_keep_city_blank", component_fee_not_whole_area=True),
        dict(name="福建土楼（永定•南靖）旅游景区", cities=["龙岩市", "漳州市"],
        source_url="https://wlt.fujian.gov.cn/zfxxgkzl/zfxxgkml/30qtyzdgkdzfxx/12zxtadf/202507/t20250709_6965674.htm",
        conclusion="components_span_cities_do_not_choose_one_or_infer_combined_ticket", component_fee_not_whole_area=True)]
    dump_lines(output / "scope-confirmations.jsonl", scopes_review)
    dump_lines(output / "price-candidates.jsonl", [guimeng, glass])
    dump_json(output / "run.json", dict(status="success", candidate_prices=2, existing_entity_matched=1,
        effective_date_ready=1, approved_price_policies=0, standard_snapshot_modified=False,
        acquisition_note="Direct local downloads failed twice; web-tool rendered text captures used for reviewed evidence, not claimed as raw-HTML crawling success",
        captures=[dict(path=p.relative_to(root).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in captures]))
    (output / "比较口径待确认.md").write_text("""# 首个真实票价试点：待确认

建议口径：普通全价游客的基础入园票，CNY，不含交通、索道、临展和体验；只有有效期覆盖2026年10月、对应到具体景区、票种清楚的记录才取得预算比较资格。优惠/免费人群单列，不把起价或组合价当普通门票。

可落实样本：沂蒙山龟蒙景区，70.00 CNY/人，临发改价格〔2026〕248号；2026-09-20发布，2026-10-01至2029-09-30有效。单程观光车50元、索道30元等不计入这张门票。该费用只适用于龟蒙子景区，不能填写给整个沂蒙山旅游区；采用前需为该子景区登记独立实体和来源，不与聚合目的地强行合并。

来源为行政定价通知，使用依据是行政性文件与具体价格事实，不冒称整站采用CC许可；仅登记文号、数值、日期和引用，不公开转载网站其他内容。法律条文依据见国家版权局《著作权法》第五条，适用判断与CC开放授权分别记录。

上海玻璃博物馆主馆60元仅为另一条参考候选：已匹配既有实体，地图链接坐标与Atlas记录相距约347米，原条目注明2026-07更新；它未给出价格生效区间，仍不进入严格的2026-10预算比较。主馆、儿童馆、迷宫、艺术馆及临展不能混成一个票种。

若试点获确认，示例：门票预算69.99元不匹配龟蒙70元票，预算70元匹配；不代表70元能覆盖观光车、索道或整趟游览费用。

当前未写入标准快照、未登记已批准price_policy_id；预算资格仍为0。数据契约6.3要求真实比较政策经人工确认后落实。本文件是具体待确认方案，不是批准记录。
""", encoding="utf-8", newline="\n")
    (output / "补充核实说明.md").write_text("""# 本轮补充核实

标准数据仍为atlas_clean_20261101_07，8430候选、31省、278条城市留空；本轮未改写标准字段或追加合并。

1. 文旅部名录明确沂蒙山旅游区跨潍坊与临沂；福建省文旅厅资料确认永定土楼在龙岩、南靖土楼在漳州。聚合景区继续保留跨市说明，不选择其中一市冒充全部所在地。具体来源见scope-confirmations.jsonl，政府页面仅作事实核验，不声明为CC开放数据集。
2. 找到龟蒙景区70元官方定价及明确生效区间，是当前最适合推进真实比较政策的样本。它属于子景区，不能给整个沂蒙山旅游区定价。试点方案、包含/排除项目及预算边界见比较口径待确认.md。
3. 新定位上海玻璃博物馆主馆60元参考报价，开放许可为CC BY-SA 4.0，条目更新月2026-07，地址与坐标证据已保存，关联到现有实体。生效区间仍缺，保留参考候选。大学博物馆免费信息未关联到现有标准实体，未据此批量填免费。
4. 本机Wikivoyage下载两次连接重置后停止重试；实际证据通过网页检索工具取得，已记录抓取方法、原始工具响应和摘要。结构化HTML采集程序有解析测试，但不能称为本轮真实HTML采集成功。

下一步计划：确认具体价格口径后，登记龟蒙独立实体与政策，再运行金额和预算边界检查；其余范围与日期不明的样本继续单列核验。全量数据与报告未推送或公开。
""", encoding="utf-8", newline="\n")
    print(json.dumps(dict(output=output.relative_to(root).as_posix(), government_fee=guimeng["amount"], museum_match_distance_m=round(distance)), ensure_ascii=False))


if __name__ == "__main__":
    main()
