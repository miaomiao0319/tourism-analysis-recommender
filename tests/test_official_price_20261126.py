import unittest

from cleaning.admission_pilot import POLICY
from cleaning.official_price_20261126 import NOTICES, URLS, price_validator


class OfficialPriceTests(unittest.TestCase):
    def test_each_notice_requires_exact_price_and_evidence(self):
        policy = {'price_policies': [{'id': POLICY, 'currency': 'CNY', 'approval_ref': 'approved'}]}
        for key, notice in NOTICES.items():
            row = dict(attraction_id=notice['id'], name=notice['name'], price_form=notice['form'],
                       price_min=notice['amount'], price_max=notice['amount'], currency='CNY',
                       price_policy_id=POLICY, source_refs={'price': ['e_notice_' + key]})
            evidence = [dict(source_ref='e_notice_' + key, source_url=URLS[key],
                             effective_from=notice['valid_from'], effective_to=notice['valid_to'])]
            with self.subTest(key=key):
                price_validator(row, evidence, policy)
                with self.assertRaises(ValueError):
                    price_validator(dict(row, price_min='999.00'), evidence, policy)
                with self.assertRaises(ValueError):
                    price_validator(row, [], policy)


if __name__ == '__main__':
    unittest.main()
