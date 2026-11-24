import unittest
from importlib.util import find_spec

from backend.app import create_app
from scripts.web_sample import BATCH, POLICY, SampleRepository


PATH = "/api/v1/recommendations"


@unittest.skipUnless(find_spec("flask"), "web dependency group is not installed")
class WebRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.repo = SampleRepository()
        self.app = create_app({"TESTING": True, "ACTIVE_BATCH_ID": BATCH}, self.repo)
        self.http = self.app.test_client()

    def post(self, **changes):
        return self.http.post(PATH, json={"batch_id": BATCH, **changes})

    def test_health_and_missing_batch(self):
        self.app.config["ACTIVE_BATCH_ID"] = ""
        health = self.http.get("/api/v1/health").get_json()
        self.assertEqual(health["data"], {"service_status": "ok"})
        self.assertIsNone(health["meta"]["batch_id"])
        response = self.http.get("/api/v1/dataset")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "DATASET_NOT_READY")

    def test_error_precedence_and_input(self):
        self.app.config["ACTIVE_BATCH_ID"] = ""
        for payload in ('{"batch_id":"a","batch_id":"b"}', '{"batch_id":"a","budget":{"a":1,"a":2}}',
                        '[]', '{"batch_id":"a","limit":true}', '{"batch_id":"a","budget":{"amount":0}}',
                        '{"batch_id":"a","mode":[]}', '{"batch_id":"a","unknown":null}'):
            with self.subTest(payload=payload):
                response = self.http.post(PATH, data=payload, content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.http.post(PATH, data="example").status_code, 415)

    def test_batch_conflict_returns_actual_meta(self):
        response = self.post(batch_id="older_batch", city_key="unknown")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["meta"]["batch_id"], BATCH)
        self.assertEqual(response.get_json()["error"]["code"], "BATCH_MISMATCH")

    def test_budget_and_unknown(self):
        for amount, expected in (("0", 0), ("59.99", 0), ("60", 1), ("69.99", 1), ("70", 2)):
            with self.subTest(amount=amount):
                response = self.post(budget={"amount": amount, "currency": "CNY", "price_policy_id": POLICY})
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["data"]
                self.assertEqual(result["candidate_count"], expected)
                self.assertEqual(result["returned_count"], expected)
        row = self.post(type_codes=["culture"]).get_json()["data"]["items"][0]["attraction"]
        self.assertEqual(row["price_form"], "unknown")

    def test_empty_and_invalid_preferences(self):
        self.assertEqual(self.post().get_json()["error"]["code"], "EMPTY_PREFERENCES")
        error = self.post(type_codes=["missing"]).get_json()["error"]
        self.assertEqual(error["code"], "INVALID_FILTER")
        self.assertNotEqual(error["message"], error["code"])

    def test_unavailable_price_policy(self):
        load = self.repo.load_dataset
        def no_policy(batch):
            ds = load(batch)
            ds["info"]["dictionaries"]["price_policies"] = []
            return ds
        self.repo.load_dataset = no_policy
        response = self.post(budget={"amount": "70", "currency": "CNY", "price_policy_id": POLICY})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "PRICE_POLICY_NOT_READY")
        self.assertEqual(self.post(city_key="linyi").status_code, 200)

    def test_interrupted_candidates_are_not_partial_results(self):
        import pymysql
        closed = []
        def broken(batch, prefs):
            try:
                yield from SampleRepository().iter_recommendation_candidates(batch, prefs)
                raise pymysql.err.OperationalError(2013, "test disconnect")
            finally:
                closed.append(True)
        self.repo.iter_recommendation_candidates = broken
        reply = self.post(province_key="shandong")
        self.assertEqual(reply.status_code, 503)
        self.assertIsNone(reply.get_json()["data"])
        self.assertEqual(closed, [True])

    def test_detail_and_protocol_errors(self):
        url = "/api/v1/attractions/phoenix"
        self.assertEqual(self.http.get(url, query_string={"batch_id": BATCH}).get_json()["data"]["evidence"][0]["source_ref"], "phoenix")
        self.assertEqual(self.http.get(url + "?batch_id=a&batch_id=b").status_code, 400)
        self.assertEqual(self.http.get("/api/v1/attractions/missing?batch_id=" + BATCH).status_code, 404)
        self.assertEqual(self.http.get(PATH).get_json()["error"]["code"], "METHOD_NOT_ALLOWED")
        self.assertEqual(self.http.get("/api/v1/missing").get_json()["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.http.get("/assets/not-real.js").status_code, 404)
