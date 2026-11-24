"""Explicit UI fixture. Never loaded by the normal Flask application."""
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
                         "sources": [], "available_statistics": [],
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
