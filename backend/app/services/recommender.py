"""Member B: cold-start AHP–TOPSIS–MMR tourism attraction recommender.

Public API: recommend(candidates, preferences, limit=10, dataset=None).
Consume A's complete candidate iterator and ready DatasetContext. No Flask/SQL/IO.
TOPSIS scores are relative to current candidates, not satisfaction probabilities.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

RULE_VERSION = "ahp-topsis-mmr-v1.1"
INDICATORS = ("interest", "grade", "price")
MODE_LABELS = {"balanced": "均衡推荐", "interest": "兴趣优先", "economy": "经济优先", "quality": "景区等级优先"}
# Reciprocal and fully consistent pairwise judgements; weight ratios 3:1.
MODE_MATRICES = {
    "balanced": ((1., 1., 1.), (1., 1., 1.), (1., 1., 1.)),
    "interest": ((1., 3., 3.), (1./3, 1., 1.), (1./3, 1., 1.)),
    "economy": ((1., 1., 1./3), (1., 1., 1./3), (3., 3., 1.)),
    "quality": ((1., 1./3, 1.), (3., 1., 3.), (1., 1./3, 1.)),
}
FIELDS = "batch_id attraction_id name country_code province_key province_name city_key city_name grade_system grade_status grade_level type_codes price_form price_min price_max currency price_basis price_policy_id price_raw source_refs collected_at".split()
_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_REGION = re.compile(r"[A-Za-z0-9_:-]{1,64}\Z")
_ALLOWED_PREF = {"country_code", "province_key", "city_key", "type_codes", "budget", "mode"}


class RecommendationError(ValueError):
    """Controlled application error; C maps code/message/details to AppError."""
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(code)
        self.code, self.message, self.details = code, message, details or {}


def fail(code, message, field=None):
    raise RecommendationError(code, message, {"field": field} if field else {})


def ahp_weights(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], float]:
    """Row-geometric-mean AHP weights with Saaty consistency check (CR < .10)."""
    n = len(matrix)
    if not (1 <= n <= 10) or any(len(row) != n for row in matrix):
        fail("INVALID_PARAMETER", "AHP 矩阵必须为 1—10 阶方阵")
    try:
        a = [[float(v) for v in row] for row in matrix]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecommendationError("INVALID_PARAMETER", "AHP 矩阵包含非数值") from exc
    for i in range(n):
        for j in range(n):
            if not math.isfinite(a[i][j]) or a[i][j] <= 0:
                fail("INVALID_PARAMETER", "AHP 比较值必须为正有限数")
            if not math.isclose(a[i][j] * a[j][i], 1., rel_tol=1e-9, abs_tol=1e-9):
                fail("INVALID_PARAMETER", "AHP 矩阵必须互反")
            if i == j and not math.isclose(a[i][j], 1., abs_tol=1e-9):
                fail("INVALID_PARAMETER", "AHP 矩阵对角线必须为 1")
    gm = [math.exp(sum(math.log(v) for v in row) / n) for row in a]
    denom = sum(gm)
    w = tuple(v / denom for v in gm)
    lambda_max = sum(sum(a[i][j] * w[j] for j in range(n)) / w[i] for i in range(n)) / n
    ri = {1: 0., 2: 0., 3: .58, 4: .90, 5: 1.12, 6: 1.24,
          7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}[n]
    cr = (max(0., (lambda_max - n) / (n - 1)) / ri) if ri else 0.
    if cr >= .10:
        fail("INVALID_PARAMETER", "AHP 一致性 CR 应小于 0.10")
    return w, cr


def amount(value, field):
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        fail("INVALID_PARAMETER", "金额必须为非负、最多两位小数的十进制字符串", field)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RecommendationError("INVALID_PARAMETER", "金额格式无效", {"field": field}) from exc


def normalize_preferences(pref, dataset):
    if not isinstance(dataset, Mapping) or not isinstance(dataset.get("meta"), Mapping) or not isinstance(dataset.get("info"), Mapping):
        fail("DATASET_NOT_READY", "尚无可用的 ready 批次")
    meta, info = dataset["meta"], dataset["info"]
    batch = meta.get("batch_id")
    if not isinstance(batch, str) or not _ID.fullmatch(batch) or meta.get("contract_version") != "1.0":
        fail("DATASET_INVALID", "批次 ID 或数据契约版本错误")
    ds = info.get("dictionaries")
    if not isinstance(ds, Mapping) or any(not isinstance(ds.get(k), list) for k in
        ("regions", "types", "grade_systems", "price_policies")):
        fail("DATASET_INVALID", "批次字典缺失或无效")
    if not isinstance(pref, Mapping) or set(pref) - _ALLOWED_PREF:
        fail("INVALID_PARAMETER", "偏好格式或字段不合法")
    p = {k: pref.get(k) for k in ("country_code", "province_key", "city_key")}
    for k, v in p.items():
        if v is not None and (not isinstance(v, str) or not (re.fullmatch(r"[A-Z]{2}", v) if k == "country_code" else _REGION.fullmatch(v))):
            fail("INVALID_PARAMETER", "地区代码格式错误", k)
    original_types = pref.get("type_codes", [])
    if not isinstance(original_types, list) or len(original_types) > 10 or any(
        not isinstance(t, str) or not _ID.fullmatch(t) for t in original_types
    ):
        fail("INVALID_PARAMETER", "type_codes 必须为不超过十个类型代码的数组", "type_codes")
    types = sorted(set(original_types))
    mode = pref.get("mode", "balanced")
    if not isinstance(mode, str) or mode not in MODE_MATRICES:
        fail("INVALID_PARAMETER", "不支持的推荐模式", "mode")
    raw_budget = pref.get("budget")
    budget, budget_value = None, None
    if raw_budget is not None:
        if not isinstance(raw_budget, Mapping) or set(raw_budget) != {"amount", "currency", "price_policy_id"}:
            fail("INVALID_PARAMETER", "budget 必须包含 amount、currency、price_policy_id", "budget")
        budget_value = amount(raw_budget.get("amount"), "budget.amount")
        currency, policy = raw_budget.get("currency"), raw_budget.get("price_policy_id")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            fail("INVALID_PARAMETER", "币种格式错误", "budget.currency")
        if not isinstance(policy, str) or not _ID.fullmatch(policy):
            fail("INVALID_PARAMETER", "价格政策 ID 无效", "budget.price_policy_id")
        budget = {"amount": f"{budget_value:.2f}", "currency": currency, "price_policy_id": policy}
    if not any(p.values()) and not types and budget is None:
        fail("EMPTY_PREFERENCES", "至少选择地区、兴趣或预算条件")
    regions = {r.get("key"): r for r in ds["regions"] if isinstance(r, Mapping)}
    for key, level in ((p["province_key"], "province"), (p["city_key"], "city")):
        if key is not None and (key not in regions or regions[key].get("level") != level or
           (p["country_code"] and regions[key].get("country_code") != p["country_code"])):
            fail("INVALID_FILTER", "所选地区与当前批次字典不一致")
    if p["province_key"] and p["city_key"] and regions[p["city_key"]].get("parent_key") != p["province_key"]:
        fail("INVALID_FILTER", "城市与省份不一致")
    if p["country_code"] and p["country_code"] not in info.get("countries", []):
        fail("INVALID_FILTER", "该国家或地区不在当前批次")
    allowed_types = {t.get("code") for t in ds["types"] if isinstance(t, Mapping)}
    if any(t not in allowed_types for t in types):
        fail("INVALID_FILTER", "类型代码不存在于本批次字典", "type_codes")
    if budget is not None:
        if not ds["price_policies"]:
            fail("PRICE_POLICY_NOT_READY", "尚无已确认的价格比较政策", "budget")
        if not any(isinstance(policy, Mapping) and policy.get("id") == budget["price_policy_id"] and
            policy.get("currency") == budget["currency"] for policy in ds["price_policies"]):
            fail("INVALID_FILTER", "票价政策或币种不匹配", "budget")
    return batch, ds, dict(p, type_codes=types, budget=budget, mode=mode), budget_value


def eligible_price(row, budget, budget_value):
    if row.get("price_form") not in ("free", "exact") or row.get("currency") != budget["currency"] or row.get("price_policy_id") != budget["price_policy_id"]:
        return None
    mn, mx = row.get("price_min"), row.get("price_max")
    if not isinstance(mn, str) or not isinstance(mx, str) or not _AMOUNT.fullmatch(mn) or not _AMOUNT.fullmatch(mx):
        return None
    lower, upper = Decimal(mn), Decimal(mx)
    if lower != upper or lower > budget_value or (row["price_form"] == "free" and lower != 0) or (
        row["price_form"] == "exact" and lower <= 0
    ):
        return None
    refs = row.get("source_refs")
    if not isinstance(refs, Mapping) or not isinstance(refs.get("price"), list) or not refs["price"]:
        return None
    return lower


def _grade(row):
    if row.get("grade_system") != "CN_A" or row.get("grade_status") != "rated":
        return 0., None
    level = row.get("grade_level")
    return (int(level[0]) / 5., level) if level in ("1A", "2A", "3A", "4A", "5A") else (0., None)


def _topsis(features, weights):
    if not features:
        return [], {}
    if len(features) == 1:
        return [1.], dict(weights)
    active = [k for k in weights if max(r[k] for r in features) - min(r[k] for r in features) > 1e-12]
    if not active:
        return [0.5] * len(features), {}
    total = sum(weights[k] for k in active)
    used = {k: weights[k] / total for k in active}
    cols = {}
    for k in active:
        norm = math.sqrt(sum(r[k] ** 2 for r in features))
        cols[k] = [used[k] * r[k] / norm for r in features]
    hi, lo = ({k: max(cols[k]) for k in active}, {k: min(cols[k]) for k in active})
    scores = []
    for i in range(len(features)):
        pos = math.sqrt(sum((cols[k][i] - hi[k]) ** 2 for k in active))
        neg = math.sqrt(sum((cols[k][i] - lo[k]) ** 2 for k in active))
        scores.append(neg / (pos + neg) if pos + neg > 1e-15 else 0.5)
    return scores, used


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.


def recommend(candidates: Iterable[Mapping[str, Any]], preferences: Mapping[str, Any],
              limit: int = 10, dataset: Mapping[str, Any] | None = None):
    """Return RecommendationResult data; C is responsible for HTTP envelope/error mapping."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        fail("INVALID_PARAMETER", "limit 必须在 1—50 之间", "limit")
    batch, ds, pref, budget_value = normalize_preferences(preferences, dataset)
    interest = frozenset(pref["type_codes"])
    mode, budget = pref["mode"], pref["budget"]
    ahp, cr = ahp_weights(MODE_MATRICES[mode])
    initial = dict(zip(INDICATORS, ahp))
    active = [k for k in INDICATORS if (k != "interest" or interest) and (k != "price" or budget is not None)]
    total = sum(initial[k] for k in active)
    available = {k: initial[k] / total for k in active}
    warnings = []
    if mode == "economy" and budget is None:
        warnings.append("未输入预算，经济优先无法启用价格指标")
    if mode == "interest" and not interest:
        warnings.append("未输入兴趣类型，兴趣优先无法启用兴趣指标")
    if budget is None and not ds["price_policies"]:
        warnings.append("当前批次暂无可比较价格政策，不进行价格排序")
    labels = {t["code"]: t.get("label") or t["code"] for t in ds["types"] if isinstance(t, Mapping) and "code" in t}
    selected, seen = [], set()
    for row in candidates:
        if not isinstance(row, Mapping) or any(f not in row for f in FIELDS):
            fail("DATASET_INVALID", "景点候选缺失标准字段")
        if row["batch_id"] != batch:
            fail("DATASET_INVALID", "景点批次与服务批次不一致")
        ident = row["attraction_id"]
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in seen:
            fail("DATASET_INVALID", "景点候选 ID 缺失、重复或不合法")
        seen.add(ident)
        if any(pref[k] and row[k] != pref[k] for k in ("country_code", "province_key", "city_key")):
            continue
        tags_raw = row["type_codes"]
        if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
            fail("DATASET_INVALID", "景点类型字段不合法")
        tags = frozenset(tags_raw)
        if interest and not (tags & interest):
            continue
        price = eligible_price(row, budget, budget_value) if budget is not None else None
        if budget is not None and price is None:
            continue
        grade, grade_label = _grade(row)
        feats = {"interest": len(tags & interest) / len(interest) if interest else 0.,
                 "grade": grade, "price": (1. - float(price / budget_value)) if budget is not None and budget_value > 0 else (1. if budget is not None else 0.)}
        reasons = []
        if pref["city_key"]:
            reasons.append("位于所选城市：" + (row.get("city_name") or pref["city_key"]))
        elif pref["province_key"]:
            reasons.append("位于所选省份：" + (row.get("province_name") or pref["province_key"]))
        elif pref["country_code"]:
            reasons.append("符合所选国家或地区：" + pref["country_code"])
        if interest:
            reasons.append("匹配兴趣：" + "、".join(labels.get(x, x) for x in sorted(tags & interest)))
        if grade_label:
            reasons.append(f"景区等级：{grade_label}（不等于游客评分）")
        if budget is not None:
            reasons.append(("已确认免费" if price == 0 else f"门票 {price:.2f} {budget['currency']}") +
                           f"，符合 {budget['amount']} {budget['currency']} 单景点门票预算")
        selected.append({"attraction": {k: row[k] for k in FIELDS}, "id": ident, "name": row["name"],
                         "tags": tags, "reasons": reasons, "features": feats})
    scores, effective = _topsis([r["features"] for r in selected], available)
    for row, score in zip(selected, scores):
        row["score"] = score
    ordered = sorted(selected, key=lambda r: (-r["score"], r["name"], r["id"]))
    for rank, row in enumerate(ordered, 1):
        row["topsis_rank"] = rank
    chosen, lam = [], 0.8
    while ordered and len(chosen) < limit:
        if not chosen:
            winner = ordered[0]
        else:
            winner = min(ordered, key=lambda r: (
                -(lam * r["score"] - (1 - lam) * max(_jaccard(r["tags"], s["tags"]) for s in chosen)),
                -r["score"], r["name"], r["id"]))
        ordered.remove(winner)
        chosen.append(winner)
    items = [{"attraction": r["attraction"], "reasons": r["reasons"],
              "topsis_score": round(r["score"], 6), "topsis_rank": r["topsis_rank"]} for r in chosen]
    algorithm_info = {
        "mode": mode, "mode_label": MODE_LABELS[mode],
        "ahp_weights": {k: round(v, 6) for k, v in initial.items()}, "ahp_cr": round(cr, 8),
        "available_weights": {k: round(v, 6) for k, v in available.items()},
        "effective_weights": {k: round(v, 6) for k, v in effective.items()},
        "mmr_lambda": lam, "warnings": warnings,
        "score_note": "TOPSIS 分数是本次候选的相对理想解贴近度，不是满意概率或游客评分。",
    }
    return {"items": items, "candidate_count": len(selected), "returned_count": len(items),
            "limit": limit, "rule_version": RULE_VERSION, "preferences": pref,
            "empty_reason": None if selected else "NO_MATCHING_CANDIDATES", "algorithm_info": algorithm_info}
