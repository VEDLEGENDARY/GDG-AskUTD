import unittest
from semantic_retrieval import WordPiece, EMBED, SemanticRetriever, DEFAULT

def chunk(cid,doc='doc001',text='Evidence'):
    return dict(chunk_id=cid,doc_id=doc,text=text,source_title='Guide',section_heading='Policy')
class SemanticTests(unittest.TestCase):
    def test_known_wordpiece_ids(self):
        t=WordPiece(EMBED/'tokenizer.json')
        self.assertEqual(t.encode('Hello world!'),(t.vocab['hello'],t.vocab['world'],t.vocab['!']))
    def test_accent_and_whitespace_normalization(self):
        t=WordPiece(EMBED/'tokenizer.json')
        self.assertEqual(t.encode('CAFÉ\tpolicy'),t.encode('cafe policy'))
    def test_pair_budget_and_segments(self):
        t=WordPiece(EMBED/'tokenizer.json'); x=t.batch([('hello '*200,'world '*300),('hi','bye')],128)
        self.assertEqual(x['input_ids'].shape,(2,128))
        self.assertEqual(int(x['attention_mask'][0].sum()),128)
        self.assertEqual(int(x['input_ids'][0,-1]),102)
        self.assertEqual(int(x['token_type_ids'][0,-1]),1)
    def test_unknown_long_word(self):
        t=WordPiece(EMBED/'tokenizer.json'); self.assertEqual(t.encode('z'*101),(100,))
    def make_r(self,rows,chunks=None):
        r=object.__new__(SemanticRetriever); r.chunks=chunks or [chunk(str(i)) for i in range(len(rows))]
        r.features=lambda query:dict(reason=None,candidates=rows)
        return r
    def test_context_budget_skips_oversized_candidate(self):
        r=self.make_r([dict(index=0,score=5,dense=0,lexical=0,cost=950),dict(index=1,score=4,dense=0,lexical=0,cost=100)])
        hits,_=r.retrieve('question',DEFAULT)
        self.assertEqual([h['chunk_id'] for h in hits],['1'])
    def test_per_document_cap(self):
        rows=[dict(index=i,score=5-i,dense=0,lexical=0,cost=100) for i in range(3)]
        hits,_=self.make_r(rows).retrieve('question',{**DEFAULT,'max_per_document':1})
        self.assertEqual(len(hits),1)
    def test_abstention_has_no_hits(self):
        r=object.__new__(SemanticRetriever);r.features=lambda query:dict(reason='Private data',candidates=[])
        self.assertEqual(r.retrieve('question',DEFAULT),([],'Private data'))
    def test_threshold_cannot_force_a_hit(self):
        r=self.make_r([dict(index=0,score=-10,dense=0,lexical=0,cost=100)])
        self.assertEqual(r.retrieve('question',DEFAULT)[0],[])
if __name__=='__main__':unittest.main()
