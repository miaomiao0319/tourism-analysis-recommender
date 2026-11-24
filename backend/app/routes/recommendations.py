import json
import re
from contextlib import closing

from flask import Blueprint, current_app, g, jsonify, request
from ..errors import AppError
from ..services.recommender import MODE_MATRICES, amount, recommend


api = Blueprint("api", __name__, url_prefix="/api/v1")
ID = r"[A-Za-z0-9_-]{1,64}"
REGION = r"[A-Za-z0-9_:-]{1,64}"
EMPTY_META = dict(batch_id=None, data_kind=None, contract_version=None)


def envelope(data=None, error=None):
    return jsonify(data=data, meta=getattr(g, "batch_meta", EMPTY_META), error=error)


def invalid(message, field=None):
    raise AppError("INVALID_PARAMETER", message, {"field": field} if field else {})


def identifier(value, pattern, field):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        invalid("标识或代码格式有误。", field)


def exact_query(*keys):
    if set(request.args) != set(keys) or any(len(values) != 1 for _, values in request.args.lists()):
        invalid("查询参数有遗漏、重复或多余项。")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            invalid("JSON 字段重复。", key)
        obj[key] = value
    return obj


def reject_constant(_):
    invalid("JSON 数值无效。")


def read_request():
    if request.mimetype != "application/json":
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。")
    try:
        body = json.loads(request.get_data().decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except (ValueError, RecursionError):
        invalid("无法读取 JSON 对象。")
    fields = {"country_code", "province_key", "city_key", "type_codes", "budget", "mode", "limit", "batch_id"}
    if not isinstance(body, dict) or set(body) - fields:
        invalid("推荐请求包含未知字段，或内容不是对象。")
    batch = body.pop("batch_id", None)
    identifier(batch, ID, "batch_id")
    limit = body.pop("limit", 10)
    if type(limit) is not int or not 1 <= limit <= 50:
        invalid("返回数量应为 1 至 50 的整数。", "limit")
    for key, pattern in (("country_code", r"[A-Z]{2}"), ("province_key", REGION), ("city_key", REGION)):
        if body.get(key) is not None:
            identifier(body[key], pattern, key)
    tags = body.get("type_codes", [])
    if not isinstance(tags, list) or len(tags) > 10:
        invalid("兴趣类型应为不超过十项的数组。", "type_codes")
    for tag in tags:
        identifier(tag, ID, "type_codes")
    mode = body.get("mode", "balanced")
    if not isinstance(mode, str) or mode not in MODE_MATRICES:
        invalid("推荐模式无效。", "mode")
    budget = body.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or set(budget) != {"amount", "currency", "price_policy_id"}:
            invalid("预算须包含金额、币种和票价口径。", "budget")
        amount(budget["amount"], "budget.amount")
        identifier(budget["currency"], r"[A-Z]{3}", "budget.currency")
        identifier(budget["price_policy_id"], ID, "budget.price_policy_id")
    return batch, body, limit


def repository():
    return current_app.extensions["tourism_repository"]


def load_batch(expected=None):
    batch = current_app.config.get("ACTIVE_BATCH_ID")
    if not batch:
        raise AppError("DATASET_NOT_READY", "尚未配置可用数据批次。")
    if not re.fullmatch(ID, batch):
        raise AppError("DATASET_INVALID", "服务配置中的批次标识无效。")
    dataset = repository().load_dataset(batch)
    meta = dataset["meta"]
    if meta.get("batch_id") != batch or meta.get("contract_version") != "1.0" or meta.get("data_kind") not in ("test", "real"):
        raise AppError("DATASET_INVALID", "数据批次与配置不一致。")
    g.batch_meta = {key: meta[key] for key in EMPTY_META}
    if expected is not None and batch != expected:
        raise AppError("BATCH_MISMATCH", "数据批次已更新，请重新读取。")
    return dataset


@api.get("/health")
def health():
    exact_query()
    return envelope({"service_status": "ok"})


@api.get("/dataset")
def dataset_info():
    exact_query()
    return envelope(load_batch()["info"])


@api.post("/recommendations")
def recommendations():
    exact_query()
    batch, preferences, limit = read_request()
    dataset = load_batch(batch)
    candidates = repository().iter_recommendation_candidates(batch, preferences)
    with closing(candidates):
        result = recommend(candidates, preferences, limit=limit, dataset=dataset)
    return envelope(result)


@api.get("/attractions/<attraction_id>")
def detail(attraction_id):
    exact_query("batch_id")
    batch = request.args["batch_id"]
    identifier(batch, ID, "batch_id")
    identifier(attraction_id, ID, "attraction_id")
    load_batch(batch)
    record = repository().get_attraction(batch, attraction_id)
    if record is None:
        raise AppError("NOT_FOUND", "当前批次中找不到此景点。")
    return envelope(record)
