import unittest
from importlib.util import find_spec
from unittest.mock import Mock

from backend.app import create_app
from scripts.web_sample import BATCH, POLICY, SampleRepository


@unittest.skipUnless(find_spec("flask"), "web dependency group is not installed")
class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.repo = SampleRepository()
        self.app = create_app({"TESTING": True, "ACTIVE_BATCH_ID": BATCH}, self.repo)
        self.http = self.app.test_client()

    def get(self, path, **params):
        return self.http.get("/api/v1/" + path, query_string={"batch_id": BATCH, **params})

    def test_list_forwards_filters_and_pagination(self):
        self.repo.list_attractions = Mock(wraps=self.repo.list_attractions)
        page = self.get("attractions", q=" 凤凰 ", max_price="60", sort="price_asc",
                        currency="CNY", price_policy_id=POLICY, page="1", page_size="1").get_json()
        self.assertEqual(page["data"]["items"][0]["attraction_id"], "phoenix")
        self.repo.list_attractions.assert_called_once_with(BATCH, dict(q="凤凰", max_price="60.00",
            currency="CNY", price_policy_id=POLICY), 1, 1, "price_asc")
        self.assertEqual(self.get("attractions", page=5).get_json()["data"]["items"], [])

    def test_invalid_pagination_and_query(self):
        for args in (dict(page="0"), dict(page_size="101"), dict(page="-1"), dict(page="1e2"),
                     dict(sort="random"), dict(extra="any"), dict(city_key="null"), dict(max_price="10.001")):
            with self.subTest(args=args):
                self.assertEqual(self.get("attractions", **args).status_code, 400)
        self.assertEqual(self.http.get("/api/v1/statistics?metric=a&metric=b&batch_id=b").status_code, 400)

    def test_batches_match_before_read(self):
        for path, args in (("attractions", {}), ("statistics", {"metric": "attraction_count"})):
            reply = self.get(path, batch_id="older", **args)
            self.assertEqual(reply.status_code, 409)
            self.assertEqual(reply.json["meta"]["batch_id"], BATCH)
            self.assertEqual(reply.json["error"]["code"], "BATCH_MISMATCH")

    def test_stat_page_reassembly_and_count_sort(self):
        args = dict(metric="attraction_count", scope="city", sort="count_desc", page_size=1)
        first, second = (self.get("statistics", page=i, **args).json["data"] for i in (1, 2))
        self.assertEqual(first["total_pages"], 2)
        self.assertEqual([first["items"][0]["value"]["count"], second["items"][0]["value"]["count"]], [2, 1])

    def test_price_context_and_metric_availability(self):
        self.assertEqual(self.get("statistics", metric="price_summary").status_code, 400)
        self.assertEqual(self.get("statistics", metric="attraction_count", scope="all", country_code="CN").status_code, 400)
        reply = self.get("statistics", metric="data_quality")
        self.assertEqual(reply.status_code, 409)
        self.assertEqual(reply.json["error"]["code"], "STATISTIC_NOT_AVAILABLE")
        ok = self.get("statistics", metric="price_summary", currency="CNY", price_policy_id=POLICY)
        self.assertEqual(ok.json["data"]["items"][0]["value"]["valid_count"], 2)

    def test_unavailable_repository(self):
        import pymysql
        self.repo.list_attractions = Mock(side_effect=pymysql.err.OperationalError("sample"))
        reply = self.get("attractions")
        self.assertEqual(reply.status_code, 503)
        self.assertEqual(reply.json["error"]["code"], "DEPENDENCY_UNAVAILABLE")
