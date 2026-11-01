"""Constructed price evidence tests; real publishing is verified separately."""
import copy
import unittest

from cleaning.admission_pilot import AID, GOV_URL, IDENTITY, POLICY, budget_matches, money, validate_price


class AdmissionPilotTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(attraction_id=AID, price_form="exact", price_min="70.00", price_max="70.00",
            currency="CNY", price_basis="test full admission", price_policy_id=POLICY,
            price_raw="test quote", source_refs={"price": ["test_quote"]})
        self.evidence = [dict(source_ref="test_quote", source_url=GOV_URL, entity_identity=IDENTITY,
            amount="70.00", currency="CNY", ticket_scope="basic_full_admission",
            effective_from="2026-10-01", effective_to="2029-09-30")]
        self.dictionaries = dict(price_policies=[dict(id=POLICY, approval_ref="constructed_test_only")])

    def test_decimal_budget_boundary_and_currency(self):
        for budget, currency, expected in (("69.99", "CNY", False), ("70", "CNY", True),
                ("0", "CNY", False), ("70", "USD", False)):
            self.assertEqual(budget_matches(self.row, budget, currency, self.evidence, self.dictionaries), expected)
        for invalid in (70.0, "NaN", "Infinity", "-1", "70.001", "1e2", "10000000000.00"):
            with self.assertRaises(ValueError):
                money(invalid)

    def test_wrong_scope_expiry_currency_or_entity_rejected(self):
        for field, value in (("ticket_scope", "cable_combo"), ("effective_to", "2026-10-30"),
                ("effective_from", "2026-10-02"), ("currency", "USD"), ("entity_identity", "aggregate")):
            evidence = copy.deepcopy(self.evidence)
            evidence[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_price(self.row, evidence, self.dictionaries)
        aggregate = dict(self.row, attraction_id="aggregate")
        with self.assertRaises(ValueError):
            validate_price(aggregate, self.evidence, self.dictionaries)

    def test_unapproved_and_unknown_never_become_free(self):
        with self.assertRaises(ValueError):
            validate_price(self.row, self.evidence, dict(price_policies=[]))
        unknown = dict(self.row, price_form="unknown")
        for key in ("price_min", "price_max", "currency", "price_basis", "price_policy_id", "price_raw"):
            unknown[key] = ""
        self.assertFalse(budget_matches(unknown, "999", "CNY", self.evidence, self.dictionaries))
        for form in ("range", "from", "conflict"):
            with self.subTest(form=form), self.assertRaises(ValueError):
                validate_price(dict(self.row, price_form=form), self.evidence, self.dictionaries)


if __name__ == "__main__":
    unittest.main()
