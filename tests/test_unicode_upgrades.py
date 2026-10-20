import tempfile
import unittest
from unittest.mock import patch
from ownsearch.textproc import normalize, tokenize, exact_tokens, ngrams
from ownsearch.spell import distance
from ownsearch.segments import SegmentBuilder, SegmentReader, NF
from tests.helpers import make_engine


class UnicodeUpgradeTests(unittest.TestCase):
    def test_forms_preserve_original_and_fold_only_search_representation(self):
        for text in ['कृत्रिम बुद्धिमत्ता','કૃત્રિમ બુદ્ધિ','中文','ภาษาไทย','İstanbul','Tiếng Việt']:
            self.assertEqual(normalize(text).original,text)
            self.assertTrue(tokenize(text))
        self.assertEqual(normalize('١२૩').folded,'123')
        self.assertEqual(normalize('क़').folded,normalize('क़').folded)
        self.assertNotIn('\u200d',normalize('क्\u200dष').folded)
        self.assertIn('\u200d',normalize('क्\u200dष').exact)
        self.assertEqual(normalize('عَرَبِيّ').folded,'عربي')
        self.assertNotEqual(normalize('café').exact,normalize('cafe').exact)
        self.assertEqual(normalize('café').folded,'cafe')
        self.assertTrue(ngrams('कृत्रिम'))

    def test_index_and_query_share_folding_and_quotes_preserve_accents(self):
        e,_=make_engine()
        e.add_document('Café menu','Café offers coffee.','https://one.example/')
        e.add_document('Cafe supplies','Cafe supplies are sold.','https://two.example/')
        self.assertTrue(e.search('cafe')['results'])
        self.assertEqual([r['url'] for r in e.search('"café"')['results']],['https://one.example/'])
        e.add_document('Running quickly','Running quickly is enjoyable.','https://three.example/')
        self.assertEqual(e.search('"run quickly"')['results'],[])

    def test_legacy_six_field_segments_remain_readable(self):
        import ownsearch.segments as segments
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(segments,'NF',6),patch.object(segments,'FIELDS',('title','headings','url','anchor','body','meta')),patch.object(segments,'F_META',5):
                b=SegmentBuilder();b.add(1,{'title':['legacy'],'body':['legacy'],'meta':['site:example']});b.write(tmp,'old')
            reader=SegmentReader(tmp,'old')
            posting=reader.decode(reader.lookup('legacy'))
            self.assertEqual(posting.tf(0,0),1)
            self.assertEqual(len(reader.lengths),NF)
            self.assertEqual(posting.tf(NF-1,0),0)

    def test_index_vocabulary_spelling_preserves_original_and_code_and_quotes(self):
        e,_=make_engine()
        e.add_document('Nebula museum','Nebula museum exhibits include a prism. Nebula welcomes visitors.','https://museum.example/')
        r=e.search('nebla museum')
        self.assertEqual(r['query'],'nebla museum')
        self.assertEqual(r['did_you_mean'],'nebula museum')
        self.assertEqual(r['results'][0]['url'],'https://museum.example/')
        self.assertEqual(e.search('"nebla museum"')['results'],[])
        self.assertNotIn('did_you_mean',e.search('nebla_handler'))
        self.assertEqual(distance('chracter','character'),1)

    def test_quoted_compatibility_characters_use_original_source(self):
        e,_=make_engine()
        url='https://ligature.example/'
        e.add_document('A ﬁne document','The ﬁne documentation uses a source ligature.',url)
        self.assertEqual(e.search('"fine"')['results'],[])
        self.assertEqual(e.search('"ﬁne"')['results'][0]['url'],url)
        source=e.store.originals([e.store.get_by_url(url)['id']])
        self.assertIn('ﬁne',next(iter(source.values()))['text'])

    def test_similar_multiword_names_do_not_fill_results(self):
        e,_=make_engine()
        e.add_document('Kumkum Bhagya characters','Kumkum Bhagya characters are listed here.','https://a.example/')
        e.add_document('Kundali Bhagya characters','Kundali Bhagya characters are listed here.','https://b.example/')
        self.assertEqual([r['url'] for r in e.search('Kumkum Bhagya')['results']],['https://a.example/'])

    def test_financial_retrieval_does_not_fill_with_sdk_or_company_profiles(self):
        e,_=make_engine()
        e.add_document('Nebula Python SDK documentation','Nebula SDK installation and Python programming examples.','https://sdk.example/')
        e.add_document('Nebula company profile','Nebula is a manufacturer founded in 1998.','https://profile.example/')
        e.add_document('Nebula stock quote','Nebula stock price quote and daily share price history.','https://quote.example/')
        result=e.search('Nebula live price',live=False)
        self.assertEqual([r['url'] for r in result['results']],['https://quote.example/'])

    def test_quoted_search_survives_merge_of_legacy_and_new_segments(self):
        import ownsearch.segments as segments
        import ownsearch.indexer as indexer
        from ownsearch.textproc import analyze
        e,_=make_engine()
        row=e.store.upsert('https://legacy.example/','Legacy phrase','Legacy phrase remains searchable.')
        with patch.object(segments,'NF',6),patch.object(segments,'FIELDS',('title','headings','url','anchor','body','meta')),patch.object(segments,'F_META',5):
            builder=SegmentBuilder()
            builder.add(row['id'],{'title':analyze('Legacy phrase'),'body':analyze('Legacy phrase remains searchable.'),'meta':[]})
            meta=builder.write(e.settings.index_dir,'legacy_segment')
        meta.update(n_deleted=0,del_file=None)
        with e.index.write_lock():
            e.index._write_manifest({'generation':1,'segments':[meta],'next_seg':1,'committed_seq':e.store.current_seq()})
            e.index._load()
        e.add_document('Modern article','Modern article about a separate topic.','https://modern.example/')
        e.optimize()
        result=e.search('"legacy phrase"',use_cache=False)
        self.assertEqual([r['url'] for r in result['results']],['https://legacy.example/'])
