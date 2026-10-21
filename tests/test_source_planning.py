"""Generic discovery regressions; fixture sources are not runtime overrides."""
import tempfile
from pathlib import Path
import unittest
from ownsearch.sourceplan import Source,load_registry,plan_sources
from ownsearch.native_search import discover_search_forms,submit_search_url,independent_url

class SourcePlanTests(unittest.TestCase):
    def test_descriptions_select_over_url_order_without_topic_switch(self):
        sources=[Source('https://one.example/','Cooking recipes and food preparation'),
                 Source('https://two.example/','Orbital navigation trajectory guidance reference')]
        plan=plan_sources('orbital guidance',sources)
        self.assertEqual(plan[0]['url'],sources[1].url)
        self.assertGreater(plan[0]['score'],plan[1]['score'])
    def test_unknown_query_does_not_drop_any_source(self):
        sources=[Source('https://one.example/','Recipes'),Source('https://two.example/','Documentation')]
        self.assertEqual(len(plan_sources('unseenidentifier427',sources)),2)
    def test_registry_is_user_editable_tsv_and_legacy_urls_remain_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp,'sources.txt');p.write_text('# comment\nhttps://one.example/\tOrbit reference\nhttps://two.example/\n')
            sources=load_registry(p)
            self.assertEqual(sources[0].description,'Orbit reference')
            self.assertEqual(sources[1].description,'')
    def test_changing_descriptions_changes_the_plan_without_code_changes(self):
        urls=['https://one.example/','https://two.example/']
        first=plan_sources('orbital guidance',[Source(urls[0],'Orbital guidance'),Source(urls[1],'Cooking')])
        second=plan_sources('orbital guidance',[Source(urls[0],'Cooking'),Source(urls[1],'Orbital guidance')])
        self.assertNotEqual(first[0]['url'],second[0]['url'])

class NativeSearchTests(unittest.TestCase):
    def test_url_comes_only_from_fetched_form_action_and_controls(self):
        forms=discover_search_forms('<form action="/lookup" method="get"><input type="hidden" name="scope" value="articles"><input type="search" name="words"></form>','https://fixture.example/root')
        self.assertEqual(submit_search_url(forms[0],'unseen alias'),'https://fixture.example/lookup?scope=articles&words=unseen+alias')
    def test_no_form_means_no_guessed_search_endpoint(self):
        self.assertEqual(discover_search_forms('<a href="/about">About</a>','https://fixture.example/'),[])
    def test_post_login_and_cross_origin_forms_are_rejected(self):
        for html in ('<form method=post><input type=search name=q></form>',
                     '<form><input type=password name=p><input type=search name=q></form>',
                     '<form action="https://elsewhere.example/find"><input type=search name=q></form>',
                     '<form><input name=message></form>'):
            self.assertEqual(discover_search_forms(html,'https://fixture.example/'),[])
    def test_search_role_text_input_supported(self):
        forms=discover_search_forms('<form role=search action="/find"><input name=term></form>','https://fixture.example/')
        self.assertEqual(submit_search_url(forms[0],'two words'),'https://fixture.example/find?term=two+words')
    def test_external_search_dependencies_are_rejected(self):
        for host in ('www.google.com','search.brave.com','api.bing.com','duckduckgo.com','search.yahoo.com'):
            self.assertIsNone(independent_url('https://'+host+'/'))
    def test_duplicate_controls_and_encoding_preserved(self):
        forms=discover_search_forms('<form action="/find?old=1"><input name=x type=hidden value=1><input name=x type=hidden value=2><input type=search name=q></form>','https://fixture.example/')
        self.assertEqual(submit_search_url(forms[0],'a&b'),'https://fixture.example/find?x=1&x=2&q=a%26b')
    def test_ambiguous_query_controls_rejected(self):
        self.assertEqual(discover_search_forms('<form><input type=search name=x><input type=search name=y></form>','https://fixture.example/'),[])

class DiscoveryPipelineTests(unittest.TestCase):
    def test_root_planning_inspects_relevant_registry_source_before_other_root(self):
        from tests.independent_fixture import Site,article
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nAllow: /') as site, tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp,'sources.txt')
            path.write_text(site.base+'/large\tCooking recipes\n'+site.base+'/guide\tOrbital guidance reference\n')
            engine=IndependentSearch(settings(sources_file=str(path),source_planning_enabled=True,max_pages_per_query=1))
            out=engine.search('orbital guidance')
            self.assertEqual(out['results'][0]['url'],site.base+'/guide')
            self.assertNotIn('/large',site.hits)
    def test_zero_match_news_links_do_not_exhaust_the_article_budget(self):
        from tests.independent_fixture import Site
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nAllow: /') as site:
            engine=IndependentSearch(settings(focused_links_enabled=True))
            out=engine.search('unseen individual',seeds=[site.base+'/'])
            self.assertEqual(out['coverage']['attempted_pages'],1)
            self.assertEqual(out['coverage']['requests'],2)
            self.assertEqual(out['results'],[])
    def test_real_native_form_discovers_alias_bearing_article(self):
        from tests.independent_fixture import Site,article
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nAllow: /') as site:
            site.rows['/catalog']=(200,'text/html',b'<html><body><form action="/lookup" method=get><input type=search name=words></form></body></html>',{})
            site.rows['/lookup?words=virelli']=(200,'text/html',b'<html><head><meta name=robots content=noindex></head><body><a href="/biography">Virelli biography</a></body></html>',{})
            site.rows['/biography']=(200,'text/html',article('Mira Virelli','Mira Virelli is an astronomer. Virelli studies orbital observations and publishes research.'),{})
            engine=IndependentSearch(settings(native_search_enabled=True,focused_links_enabled=True))
            out=engine.search('who is virelli?',seeds=[site.base+'/catalog'],answer_mode=True)
            self.assertIn('/lookup?words=virelli',site.hits)
            self.assertEqual(out['results'][0]['url'],site.base+'/biography')
            self.assertIsNotNone(out['answer'])
    def test_native_heading_links_can_reveal_an_alias_without_title_inheritance(self):
        from tests.independent_fixture import Site,article
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nAllow: /') as site:
            site.rows['/catalog']=(200,'text/html',b'<html><body><form action="/lookup"><input type=search name=words></form></body></html>',{})
            site.rows['/lookup?words=harbor']=(200,'text/html',b'<html><head><meta name=robots content=noindex></head><body><h2><a href="/biography">Mira Virelli</a></h2></body></html>',{})
            site.rows['/biography']=(200,'text/html',article('Mira Virelli','Mira Virelli is an astronomer whose colleagues call her Harbor. Harbor studies stellar observations.'),{})
            out=IndependentSearch(settings(native_search_enabled=True,focused_links_enabled=True)).search('who is harbor?',seeds=[site.base+'/catalog'])
            self.assertEqual(out['results'][0]['url'],site.base+'/biography')
            self.assertEqual(out['results'][0]['title'],'Mira Virelli')

    def test_opaque_declared_sitemap_link_remains_reachable(self):
        from tests.independent_fixture import Site
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site() as site:
            out=IndependentSearch(settings(focused_links_enabled=True)).search('orbital guidance',seeds=[site.base+'/'])
            self.assertIn(site.base+'/mapped',{row['url'] for row in out['results']})
    def test_unrelated_links_from_cached_pages_are_filtered_too(self):
        from tests.independent_fixture import Site
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nAllow: /') as site:
            engine=IndependentSearch(settings(focused_links_enabled=True,max_pages_per_query=1))
            engine.search('orbital guidance',seeds=[site.base+'/'])
            before=dict(site.hits)
            out=engine.search('unseen individual',seeds=[site.base+'/'])
            self.assertEqual(dict(site.hits),before)
            self.assertEqual(out['coverage']['requests'],0)

    def test_native_form_target_still_obeys_robots(self):
        from tests.independent_fixture import Site
        from tests.test_independent import settings
        from ownsearch.coordinator import IndependentSearch
        with Site(robots='User-agent: *\nDisallow: /lookup') as site:
            site.rows['/catalog']=(200,'text/html',b'<html><body><form action="/lookup"><input type=search name=words></form></body></html>',{})
            out=IndependentSearch(settings(native_search_enabled=True)).search('virelli',seeds=[site.base+'/catalog'])
            self.assertNotIn('/lookup?words=virelli',site.hits)
            self.assertTrue(any(row['status']=='robots' for row in out['crawl_status']))
