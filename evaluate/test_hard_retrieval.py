import unittest
from types import SimpleNamespace
import numpy as np
from hard_retrieval import FacetRetriever,requests,reject_reason
from passage_support import fit,predict
class HardRetrievalTests(unittest.TestCase):
    def sem(self):
        chunks=[dict(source_title='B.S. in Computer Science Degree Plan (2025-2026)',section_heading='Overview'),dict(source_title='B.S. in Computer Science Degree Plan (2026-2027)',section_heading='Overview')]
        return SimpleNamespace(chunks=chunks,years={'2025','2026','2027'})
    def router(self):
        r=object.__new__(FacetRetriever)
        r.doc_titles={'cs25':'B.S. in Computer Science Degree Plan (2025-2026)','cs26':'B.S. in Computer Science Degree Plan (2026-2027)','se25':'B.S. in Software Engineering Degree Plan (2025-2026)','ce25':'B.S. in Computer Engineering (2025-2026)'}
        return r
    def test_comparison_routes_editions_independently(self):
        self.assertEqual(set(self.router().route('Compare CS degree plans for 2025-2026 and 2026-2027')),{'cs25','cs26'})
    def test_negative_major_is_not_requested(self):
        self.assertEqual(set(self.router().route('For 2025-2026 compare computer science and software engineering plans. Do not substitute computer engineering.')),{'cs25','se25'})
    def test_supported_year_comparison_is_not_rejected(self):
        self.assertIsNone(reject_reason('Compare CS degree plans for 2025-2026 and 2026-2027',self.sem()))
    def test_unpublished_plan_is_rejected_by_metadata(self):
        self.assertIsNotNone(reject_reason('For the 2045-2046 CS degree plan what hours are required?',self.sem()))
    def test_private_financial_amount_needs_records(self):
        self.assertIsNotNone(reject_reason('Exactly how many dollars of my financial aid must I repay?',self.sem()))
    def test_unidentified_course_requires_input(self):
        self.assertIsNotNone(reject_reason('Will an unspecified course meet my requirement?',self.sem()))
    def test_public_financial_rules_are_not_blanket_rejected(self):
        self.assertIsNone(reject_reason('What is the financial aid refund policy?',self.sem()))
    def test_each_direct_request_gets_a_facet(self):
        result=requests('When is registration, and what documents do I need?')
        self.assertGreaterEqual(len(result),3)
    def test_filter_outputs_probabilities_for_new_numeric_features(self):
        x=np.array([[0.,0.],[.1,.1],[1.,1.],[.9,.9]]);y=np.array([0.,0.,1.,1.])
        model=fit(x,y,.01);p=predict(np.array([[.05,.05],[.95,.95]]),model)
        self.assertTrue(np.isfinite(p).all());self.assertGreater(p[1],p[0]);self.assertTrue(((p>0)&(p<1)).all())
if __name__=='__main__':unittest.main()
