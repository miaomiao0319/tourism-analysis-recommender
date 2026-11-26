"""Read-only check of the six public HTTP endpoints after deployment."""
import argparse
import json
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


def verify(base_url, expected_batch):
    def call(path, params=None, body=None):
        url = base_url.rstrip("/") + "/api/v1/" + path
        if params:
            url += "?" + urlencode(params)
        req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"} if body is not None else {})
        with urlopen(req, timeout=30) as r:
            reply = json.load(r)
        if reply.get("error") is not None:
            raise RuntimeError(reply["error"])
        if path != "health" and reply["meta"]["batch_id"] != expected_batch:
            raise RuntimeError("响应批次与指定批次不同")
        return reply["data"]

    if call("health")["service_status"] != "ok":
        raise RuntimeError("服务未响应")
    dataset = call("dataset")
    q = {"batch_id": expected_batch}
    rows = call("attractions", {**q, "page_size": 1})
    if not rows["items"] or rows["total"] != dataset["standard_count"]:
        raise RuntimeError("列表总数与批次信息不一致或无可检查样本")
    ident = rows["items"][0]["attraction_id"]
    if call("attractions/" + quote(ident, safe=""), q)["attraction"]["attraction_id"] != ident:
        raise RuntimeError("详情标识不一致")
    stats = call("statistics", {**q, "metric": "attraction_count", "scope": "all"})
    if len(stats["items"]) != 1 or stats["items"][0]["value"]["count"] != rows["total"]:
        raise RuntimeError("总体统计与明细数量不一致")
    rec = call("recommendations", body={**q, "country_code": dataset["countries"][0], "limit": 1})
    if rec["returned_count"] != 1 or rec["items"][0]["attraction"]["batch_id"] != expected_batch:
        raise RuntimeError("推荐返回的批次或数量不一致")
    print(f"6 个接口通过 · {expected_batch} · {rows['total']} 条候选记录。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--expected-batch", required=True)
    args = parser.parse_args()
    verify(args.base_url, args.expected_batch)
