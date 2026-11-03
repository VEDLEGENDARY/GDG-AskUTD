import unittest
from types import SimpleNamespace
from instruction_retrieval import decode,clip

def c(cid,text='Policy evidence.'):
 return dict(chunk_id=cid,doc_id='doc001',text=text,source_title='Catalog',section_heading='Policy')
class InstructionSelectionTests(unittest.TestCase):
 def reader(self,chunks):return SimpleNamespace(s=SimpleNamespace(chunks=chunks))
 def test_only_supplied_passage_aliases_are_accepted(self):
  chunks=[c('a'),c('b')];r=self.reader(chunks)
  hits,reason,fallback=decode('{"answerable":true,"selected":["A","UNKNOWN","A"]}',{'A':0,'B':1},r,[])
  self.assertEqual([h['chunk_id'] for h in hits],['a']);self.assertFalse(fallback)
 def test_invalid_json_is_explicit_fallback(self):
  base=[c('a')];hits,reason,fallback=decode('not json',{'A':0},self.reader(base),base)
  self.assertTrue(fallback);self.assertEqual(hits,base)
 def test_private_request_can_abstain(self):
  hits,reason,fallback=decode('{"answerable":false,"selected":[]}',{},self.reader([]),[])
  self.assertEqual(hits,[]);self.assertIsNotNone(reason);self.assertFalse(fallback)
 def test_selected_passages_obey_context_limit(self):
  chunks=[c('a','x'*2100),c('b','y'*2100)]
  hits,reason,fallback=decode('{"answerable":true,"selected":["A","B"]}',{'A':0,'B':1},self.reader(chunks),[])
  self.assertEqual(len(hits),1);self.assertLessEqual(sum(h['estimated_tokens'] for h in hits),900)
 def test_packet_excerpt_is_literal_text(self):
  text='One sentence. Another useful sentence about deadlines. Last sentence.'
  result=clip(text,'deadline',45)
  self.assertNotIn('invented',result);self.assertTrue(all(piece in text for piece in result.split(' ... ')))
if __name__=='__main__':unittest.main()
