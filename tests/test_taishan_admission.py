import unittest

from cleaning.taishan_admission import ATTRACTION, HTML_URL, PDF_URL, price_validator
from cleaning.admission_pilot import POLICY


class TaishanAdmissionTests(unittest.TestCase):
    def test_reviewed_price_requires_matching_policy_and_both_sources(self):
        row = dict(attraction_id=ATTRACTION, price_form='exact', price_min='115.00',
                   price_max='115.00', currency='CNY', price_policy_id=POLICY,
                   source_refs={'price': ['e_taishan_notice', 'e_taishan_ticket']})
        evidence = [dict(source_ref='e_taishan_notice', source_url=PDF_URL,
                         effective_from='2024-01-01', effective_to='2026-12-31'),
                    dict(source_ref='e_taishan_ticket', source_url=HTML_URL)]
        dictionaries = {'price_policies': [dict(id=POLICY, currency='CNY', approval_ref='approval')]}
        price_validator(row, evidence, dictionaries)
        for changed, refs in ((dict(row, price_min='114.00'), evidence),
                              (row, evidence[:1]),
                              (row, [dict(evidence[0], effective_to='2026-09-30'), evidence[1]])):
            with self.subTest(changed=changed, refs=refs), self.assertRaises(ValueError):
                price_validator(changed, refs, dictionaries)


if __name__ == '__main__':
    unittest.main()
