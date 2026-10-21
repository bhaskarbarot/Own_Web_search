"""Source-bound rendering regressions, independent of provider availability."""
import unittest

from ownsearch.webmodels import WebCandidate


class Phase2SnippetTests(unittest.TestCase):
    def item(self, passage):
        item = WebCandidate('A technical guide', 'https://docs.example.org/guide',
                            'The original provider excerpt remains available.', 'fixture')
        item.evidence = [{'text': passage, 'score': 2.5, 'matched_terms': 2}]
        return item

    def test_confirmed_fixed_width_cut_does_not_split_a_word(self):
        source = 'A complete explanatory sentence. ' + 'xylophones ' * 100
        rendered = self.item(source).result(1)['snippet']
        body = rendered[:-1] if rendered.endswith('…') else rendered
        self.assertTrue(source.startswith(body))
        self.assertLessEqual(len(rendered), 600)
        self.assertFalse(body and body[-1].isalnum() and source[len(body)].isalnum())

    def test_rendering_retains_passage_source_and_score(self):
        item = self.item('A complete explanatory sentence. ' + 'xylophones ' * 100)
        text = item.evidence[0]['text']
        snippet = item.snippet
        item.score = 4.75
        rendered = item.result(3, explain=True)
        self.assertEqual(item.evidence[0]['text'], text)
        self.assertEqual(item.evidence[0]['score'], 2.5)
        self.assertEqual(item.snippet, snippet)
        self.assertEqual(rendered['score'], 4.75)
        self.assertEqual(rendered['rank'], 3)
        self.assertEqual(rendered['url'], item.url)

    def test_short_evidence_and_provider_only_snippets_are_unchanged(self):
        text = 'A short complete sentence.'
        self.assertEqual(self.item(text).result(1)['snippet'], text)
        item = self.item(text)
        item.evidence = []
        item.snippet = 'source excerpt ' * 100
        self.assertEqual(item.result(1)['snippet'], item.snippet)

    def test_last_complete_sentence_within_budget_is_used(self):
        from ownsearch.snippet import sentence_excerpt
        text = 'First sentence. Second sentence! ' + 'longword ' * 100
        self.assertEqual(sentence_excerpt(text, 70), 'First sentence. Second sentence!…')

    def test_long_sentence_uses_whole_word_fallback(self):
        from ownsearch.snippet import sentence_excerpt
        text = 'orbital sensor calibration ' * 100
        rendered = sentence_excerpt(text, 70)
        body = rendered.removesuffix('…')
        self.assertTrue(text.startswith(body))
        self.assertTrue(text[len(body)].isspace())
        self.assertTrue(rendered.endswith('…'))
        self.assertLessEqual(len(rendered), 70)

    def test_sentence_boundary_does_not_hide_matching_query_terms(self):
        from ownsearch.snippet import sentence_excerpt
        from ownsearch.textproc import analyze
        text = 'An introductory sentence. ' + 'orbital sensor calibration ' * 100
        rendered = sentence_excerpt(text, 70, query_terms=analyze('sensor calibration'))
        self.assertIn('sensor', rendered)
        self.assertTrue(rendered.endswith('…'))
        self.assertTrue(text.startswith(rendered[:-1]))
        self.assertTrue(text[len(rendered) - 1].isspace())

    def test_unbroken_long_token_is_not_presented_as_a_different_identifier(self):
        from ownsearch.snippet import sentence_excerpt
        self.assertEqual(sentence_excerpt('SupercalifragilisticIdentifier' * 50, 50), '…')

    def test_unicode_punctuation_and_closing_quotes(self):
        from ownsearch.snippet import sentence_excerpt
        for sentence in ('यह पूरा वाक्य है।', '這是一個完整的句子。', 'هذه جملة كاملة!', 'He said “complete.”'):
            with self.subTest(sentence=sentence):
                text = sentence + ' ' + 'continuedword ' * 100
                rendered = sentence_excerpt(text, len(sentence) + 15)
                self.assertEqual(rendered, sentence + '…')

    def test_tiny_budget_empty_text_and_combining_characters(self):
        from ownsearch.snippet import sentence_excerpt
        self.assertEqual(sentence_excerpt('', 1), '')
        self.assertEqual(sentence_excerpt('longer text', 1), '…')
        text = 'cafe\u0301 ' * 50
        rendered = sentence_excerpt(text, 17)
        body = rendered.removesuffix('…')
        self.assertTrue(text.startswith(body))
        self.assertTrue(text[len(body)].isspace())
        with self.assertRaises(ValueError):
            sentence_excerpt('text', 0)

    def test_repeated_rendering_is_stable(self):
        item = self.item('Complete sentence. ' + 'xylophone ' * 100)
        self.assertEqual(item.result(1), item.result(1))

    def test_measurement_distinguishes_a_truncated_match_from_a_complete_word(self):
        from scripts.eval_phase2_snippets import complete_word_prefix, inspect_excerpt
        source = 'Inventory and sales records.'
        old = 'Inventory and sale'
        self.assertTrue(inspect_excerpt(source, old)['mid_word_end'])
        self.assertEqual(complete_word_prefix(source, old), 'Inventory and ')
        self.assertEqual(complete_word_prefix(source, 'Inventory and sales…'), 'Inventory and sales')


if __name__ == '__main__':
    unittest.main()
