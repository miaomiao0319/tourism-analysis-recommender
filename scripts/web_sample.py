"""Explicit UI fixture. Never loaded by the normal Flask application."""
from decimal import Decimal

BATCH = "test_c_travel_guide"
POLICY = "test_october_ticket"
STAMP = "2026-11-24T00:00:00Z"
RATE_SOURCES = {
    "phoenix": ("朝阳市发展改革委", "https://fgw.chaoyang.gov.cn/html/CYFGW/202512/0176783480557782.html", "2025-12-10"),
    "guimeng": ("临沂市发展改革委", "https://www.linyi.gov.cn/info/3442/496729.htm", "2026-09-20"),
}
LOCATIONS = {
    "liaoning": ("辽宁省", "chaoyang", "朝阳市"),
    "shandong": ("山东省", "linyi", "临沂市"),
}


def sample_row(key, name, province, price, basis, tags):
    province_name, city, city_name = LOCATIONS[province]
    return dict(batch_id=BATCH, attraction_id=key, name=name, country_code="CN",
                province_key=province, province_name=province_name, city_key=city, city_name=city_name,
                grade_system="UNKNOWN", grade_status="unknown", grade_level=None, type_codes=tags,
                price_form="exact" if price else "unknown", price_min=price, price_max=price,
                currency="CNY" if price else None, price_basis=basis, price_policy_id=POLICY if price else None,
                price_raw=basis, source_refs={"price": [key] if price else []}, collected_at=STAMP)


ROWS = [
    sample_row("phoenix", "朝阳凤凰山", "liaoning", "60.00", "旺季基础门票，观光车另计", ["nature"]),
    sample_row("guimeng", "沂蒙山龟蒙景区", "shandong", "70.00", "基础门票，观光车和索道另计", ["nature"]),
    sample_row("sample_trail", "山间古道（示例）", "shandong", None, None, ["culture"]),
]


class SampleRepository:
    def load_dataset(self, batch):
        if batch != BATCH:
            raise ValueError("DATASET_NOT_READY")
        regions = []
        for province, (name, city, city_name) in LOCATIONS.items():
            for key, label, level, parent in ((province, name, "province", None), (city, city_name, "city", province)):
                regions.append(dict(key=key, name=label, country_code="CN", level=level, parent_key=parent,
                                    map_code=None, map_resource=None))
        types = [dict(code=k, label=v, definition=v, method="rule", basis="页面构造样例")
                 for k, v in (("nature", "自然山岳"), ("culture", "人文古迹"))]
        return {"meta": {"batch_id": BATCH, "data_kind": "test", "contract_version": "1.0"},
                "info": {"standard_count": len(ROWS), "data_cutoff_month": "2026-10", "created_at": STAMP,
                         "countries": ["CN"], "quality": {"notes": "3 条构造样本，地区与类型用于测试页面交互。"},
                         "sources": [], "available_statistics": [dict(metric=m, scope=s, currency="CNY" if m.startswith("price_") else None,
                                                           price_policy_id=POLICY if m.startswith("price_") else None)
                                                   for m, s in SAMPLE_STATS],
                         "dictionaries": {"regions": regions, "types": types, "grade_systems": [],
                                          "price_policies": [{"id": POLICY, "currency": "CNY", "ticket_basis": "基础门票",
                                                              "eligibility_rule": "样例中的可比基础门票"}]}}}

    def iter_recommendation_candidates(self, batch, preferences):
        if batch != BATCH:
            raise ValueError("DATASET_NOT_READY")
        yield from ROWS

    def get_attraction(self, batch, attraction_id):
        if batch != BATCH:
            raise ValueError("DATASET_NOT_READY")
        for row in ROWS:
            if row["attraction_id"] == attraction_id:
                evidence = []
                if attraction_id in RATE_SOURCES:
                    label, url, date = RATE_SOURCES[attraction_id]
                    evidence.append(dict(source_ref=attraction_id, source_id=label, source_url=url,
                                         collected_at=STAMP, source_date=date, source_date_kind="published"))
                return dict(attraction=row, evidence=evidence)
        return None

    def list_attractions(self, batch, filters, page=1, page_size=20, sort="name_asc"):
        rows = list(self.iter_recommendation_candidates(batch, filters))
        for key in ("country_code", "province_key", "city_key", "grade_system", "grade_status", "grade_level"):
            if key in filters:
                rows = [r for r in rows if r[key] == filters[key]]
        if filters.get("q"):
            rows = [r for r in rows if filters["q"] in r["name"]]
        if "type_code" in filters:
            rows = [r for r in rows if filters["type_code"] in r["type_codes"]]
        if "max_price" in filters or sort != "name_asc":
            if filters.get("price_policy_id") != POLICY or filters.get("currency") != "CNY":
                raise ValueError("INVALID_FILTER")
            rows = [r for r in rows if r["price_form"] in ("free", "exact")]
            if "max_price" in filters:
                rows = [r for r in rows if Decimal(r["price_min"]) <= Decimal(filters["max_price"])]
        rows.sort(key=lambda r: (r["name"], r["attraction_id"]))
        if sort != "name_asc":
            rows.sort(key=lambda r: Decimal(r["price_min"]), reverse=sort == "price_desc")
        return sample_page(rows, page, page_size)

    def list_statistics(self, batch, query, page=1, page_size=20, sort="key_asc"):
        self.load_dataset(batch)
        metric, scope = query["metric"], query["scope"]
        entries = SAMPLE_STATS.get((metric, scope))
        if entries is None:
            raise ValueError("STATISTIC_NOT_AVAILABLE")
        rows = []
        for dimensions, value in entries:
            dims = dict(scope=scope, **dimensions)
            if metric.startswith("price_"):
                dims.update(currency="CNY", price_policy_id=POLICY)
            if all(dims.get(k) == v for k, v in query["filters"].items()):
                rows.append(dict(batch_id=batch, engine="spark_sql", metric=metric,
                                 dimensions=dims, status="ok", value=value))
        if sort == "count_desc":
            rows.sort(key=lambda r: -r["value"]["count"])
        return sample_page(rows, page, page_size)


def sample_page(rows, page, page_size):
    start = (page - 1) * page_size
    return dict(items=rows[start:start + page_size], total=len(rows), page=page,
                page_size=page_size, total_pages=(len(rows) + page_size - 1) // page_size)


# Recorded test examples for the three UI rows. No offline engine is run by this fixture.
SAMPLE_STATS = {
    ("attraction_count", "all"): [({}, {"count": 3})],
    ("attraction_count", "province"): [({"country_code": "CN", "province_key": k}, {"count": n})
                                        for k, n in (("liaoning", 1), ("shandong", 2))],
    ("attraction_count", "city"): [({"country_code": "CN", "city_key": k}, {"count": n})
                                    for k, n in (("chaoyang", 1), ("linyi", 2))],
    ("attraction_count", "grade"): [({"country_code": "CN", "grade_system": "UNKNOWN",
                                      "grade_status": "unknown", "grade_level": None}, {"count": 3})],
    ("price_summary", "all"): [({}, dict(candidate_count=3, valid_count=2, coverage="0.666667",
                                          min="60.00", max="70.00", mean="65.00"))],
    ("price_histogram", "all"): [({}, dict(valid_count=2, bins=[
        dict(lower="0.00", upper="70.00", count=1), dict(lower="70.00", upper=None, count=1)]))],
}
