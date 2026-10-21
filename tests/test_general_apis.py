"""Optional general index contracts; no external requests or real credentials."""
import json
import time
import threading
import unittest
from unittest.mock import patch
from ownsearch.config import Settings
from ownsearch.fetcher import Fetcher,FetchResult
from ownsearch.generalapis import MarginaliaWebProvider
from ownsearch.webmodels import WebCandidate,WebRequest
from ownsearch.query import parse_query
from ownsearch.webproviders import configured

def request():
    return WebRequest('orbital sensor calibration',parse_query('orbital sensor calibration'),threading.Event())


class GeneralApiTests(unittest.TestCase):
    def test_marginalia_is_disabled_without_key(self):
        self.assertNotIn('marginalia',[p.name for p in configured(Settings())])
    def test_marginalia_preserves_actual_license_and_uses_header_key(self):
        p=MarginaliaWebProvider(Settings(marginalia_api_key='fixture-key'))
        data={'license':'CC-BY-NC-SA 4.0','results':[{'url':'https://pages.example.org/real','title':'Sensor','description':'Orbital sensor'}]}
        req=request()
        with patch.object(Fetcher,'fetch',return_value=FetchResult('','',200,{},json.dumps(data).encode())) as fetch:
            batch=p.search(req,time.monotonic()+1)
        self.assertNotIn('fixture-key',fetch.call_args.args[0])
        self.assertEqual(fetch.call_args.kwargs['extra_headers']['API-Key'],'fixture-key')
        self.assertEqual(WebCandidate.from_row(batch.rows[0],p.name,1).provenance[0]['license'],'CC-BY-NC-SA 4.0')
    def test_marginalia_refuses_credentials_over_plain_http(self):
        p=MarginaliaWebProvider(Settings(marginalia_api_key='fixture-key',marginalia_api_url='http://api.example.org/search'))
        with patch.object(Fetcher,'fetch') as fetch:
            with self.assertRaisesRegex(Exception,'require HTTPS'):p.search(request(),time.monotonic()+1)
            fetch.assert_not_called()
