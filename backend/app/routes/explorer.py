"""Public GET endpoints for the published batch; all database work remains in A's repository."""
import re

from flask import Blueprint, request
from analysis.common import COUNT_DIMENSIONS
from ..errors import AppError
from ..repositories.attractions import LIST_FILTERS
from ..services.recommender import amount
from .recommendations import ID, REGION, envelope, identifier, invalid, load_batch, repository

explorer = Blueprint("explorer", __name__, url_prefix="/api/v1")
DIMENSIONS = {"country_code", "province_key", "city_key", "grade_system", "grade_status",
              "grade_level", "type_code", "currency", "price_policy_id"}


def number(params, field, default, maximum):
    value = params.pop(field, str(default))
    if not re.fullmatch(r"[0-9]+", value) or len(value.lstrip("0")) > 10:
        invalid("分页参数应为范围内的正整数。", field)
    parsed = int(value.lstrip("0") or "0")
    if not 1 <= parsed <= maximum:
        invalid("分页参数超出允许范围。", field)
    return parsed


def read_query(allowed, default_sort):
    args = request.args
    if set(args) - allowed - {"page", "page_size", "sort", "batch_id"} or any(len(v) != 1 for _, v in args.lists()):
        invalid("出现未知或重复的查询参数。")
    params = args.to_dict()
    batch = params.pop("batch_id", None)
    identifier(batch, ID, "batch_id")
    page = number(params, "page", 1, 2147483647)
    size = number(params, "page_size", 20, 100)
    sort = params.pop("sort", default_sort)
    for key, val in params.items():
        if key == "q":
            params[key] = val.strip()
            if len(params[key]) > 100:
                invalid("景点名称最多 100 字。", key)
        elif key == "max_price":
            params[key] = format(amount(val, key), ".2f")
        elif key in ("province_key", "city_key", "country_code", "currency"):
            fmt = {"province_key": REGION, "city_key": REGION, "country_code": r"[A-Z]{2}", "currency": r"[A-Z]{3}"}
            identifier(val, fmt[key], key)
        elif not val or val == "null":
            invalid("请省略未使用的筛选项。", key)
        elif key in ("type_code", "price_policy_id"):
            identifier(val, ID, key)
        if key != "q" and val == "null":
            invalid("请省略未使用的筛选项。", key)
    return batch, params, page, size, sort


def price_pair(params, required):
    has = ("currency" in params, "price_policy_id" in params)
    if has[0] != has[1] or (required and not has[0]):
        invalid("价格条件需要同时提供币种与票价口径。")


@explorer.get("/attractions")
def listings():
    batch, filters, page, size, sort = read_query(LIST_FILTERS, "name_asc")
    if sort not in ("name_asc", "price_asc", "price_desc"):
        invalid("不支持的景点排序。", "sort")
    priced = "max_price" in filters or sort != "name_asc"
    price_pair(filters, priced)
    if not priced and "currency" in filters:
        invalid("单独的票价口径需要配合价格条件。")
    load_batch(batch)
    return envelope(repository().list_attractions(batch, filters, page, size, sort))


@explorer.get("/statistics")
def statistics():
    batch, filters, page, size, sort = read_query(DIMENSIONS | {"metric", "scope"}, "key_asc")
    metric, scope = filters.pop("metric", None), filters.pop("scope", "all")
    if metric not in {"attraction_count", "price_summary", "price_histogram", "data_quality"}:
        invalid("缺少或不支持该统计指标。", "metric")
    count_scopes = COUNT_DIMENSIONS if metric == "attraction_count" else {"all": ()}
    if metric in ("price_summary", "price_histogram"):
        count_scopes = {key: COUNT_DIMENSIONS[key] for key in ("all", "city", "grade")}
    if scope not in count_scopes:
        invalid("该指标不支持所选统计范围。", "scope")
    dimensions = set(count_scopes[scope]) - {"scope"}
    if metric in ("price_summary", "price_histogram"):
        dimensions.update(("currency", "price_policy_id"))
    if set(filters) - dimensions or sort not in (("key_asc", "count_desc") if metric == "attraction_count" else ("key_asc",)):
        raise AppError("INVALID_FILTER", "筛选条件或排序不适用于该统计范围。")
    price_pair(filters, False)
    data = load_batch(batch)
    if metric in ("price_summary", "price_histogram") and data["info"]["dictionaries"]["price_policies"]:
        price_pair(filters, True)
    query = {"metric": metric, "scope": scope, "filters": filters}
    return envelope(repository().list_statistics(batch, query, page, size, sort))
