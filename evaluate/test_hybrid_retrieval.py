import json,unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from hybrid_retrieval import Hybrid,record_reason
from record_classifier import RecordDetector,features
class HybridTests(unittest.TestCase):
    def make_hybrid(self,costs,docs=None):
        r=object.__new__(Hybrid)
        r.s=SimpleNamespace(chunks=[dict(chunk_id=str(i),doc_id=(docs or ['doc001']*len(costs))[i],text='Evidence') for i in range(len(costs))],costs=costs)
        r.prepare=lambda q:dict(reason=None,indices=list(range(len(costs))),ce=np.array([.9]*len(costs)),lex=np.array([[.9]*len(costs)]))
        return r
    def config(self):return dict(semantic_weight=.5,gap=.3,min_score=.1,extra=4,top_k=6,coverage_ratio=.95)
    def test_extra_passages_obey_total_budget(self):
        hits,_=self.make_hybrid([400]*5).retrieve('A question',self.config())
        self.assertEqual(len(hits),2);self.assertLessEqual(sum(c['estimated_tokens'] for c in hits),900)
    def test_extra_passages_obey_document_cap(self):
        hits,_=self.make_hybrid([100]*5).retrieve('A question',self.config());self.assertEqual(len(hits),3)
    def test_detector_can_reject_before_selection(self):
        r=self.make_hybrid([100]);r.detector=SimpleNamespace(reason=lambda q:'Private record required')
        self.assertEqual(r.retrieve('A question',self.config()),([],'Private record required'))
    def detector(self):
        model=SimpleNamespace(embed=lambda qs:np.zeros((len(qs),2)))
        path=Mock();path.read_text.return_value=json.dumps(dict(weights=[0.]*11+[4.],threshold=.7))
        return RecordDetector.load(model,path)
    def test_frozen_classifier_supports_new_questions(self):
        self.assertIsNotNone(self.detector().reason('What is my current GPA?'))
    def test_public_questions_are_not_rejected_by_record_classifier(self):
        self.assertIsNone(self.detector().reason('What is the minimum GPA for a graduate degree?'))
    def test_procedural_help_is_not_rejected_by_record_classifier(self):
        self.assertIsNone(self.detector().reason('How can I check my enrollment appointment?'))
    def test_actual_account_action_needs_a_tool(self):
        self.assertIsNotNone(record_reason('Actually withdraw me from CS 1337.',{'2026'}))
if __name__=='__main__':unittest.main()
