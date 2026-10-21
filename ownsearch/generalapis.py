"""Optional keyed general indexes. No accounts, keys or charges are provisioned."""
from urllib.parse import urlencode
from datetime import datetime,timezone
from .webproviders import JsonProvider, ProviderError, SourceBatch, provider_query


class MarginaliaWebProvider(JsonProvider):
    name='marginalia'
    minimum_interval=1.0

    def search(self,request,deadline):
        if request.search_type!='web':return SourceBatch([],['Marginalia adapter supports web results only.'])
        if not self.settings.marginalia_api_key:raise ProviderError('Marginalia key is not configured.')
        query=provider_query(request)
        data=self.request(request,self.settings.marginalia_api_url+'?'+urlencode(
            {'query':query,'count':min(20,self.settings.live_max_candidates),'dc':3,'nsfw':1}),
            deadline,headers={'API-Key':self.settings.marginalia_api_key})
        if not isinstance(data.get('results'),list):raise ProviderError('Marginalia returned an invalid results array.')
        license=data.get('license')
        rows=[{'url':item.get('url'),'title':item.get('title'),'snippet':item.get('description'),
               'source_query':query,'source_license':license}
              for item in data['results'][:self.settings.live_max_candidates] if isinstance(item,dict)]
        return SourceBatch(rows)


class MojeekWebProvider(JsonProvider):
    name='mojeek'
    minimum_interval=1.0

    def search(self,request,deadline):
        if request.search_type!='web':return SourceBatch([],['Mojeek adapter supports web results only.'])
        if not self.settings.mojeek_api_key:raise ProviderError('Mojeek key is not configured.')
        if not self.settings.mojeek_api_url.startswith('https://'):raise ProviderError('Mojeek credentialed endpoint requires HTTPS.')
        query=provider_query(request)
        # The official API requires a query-string key; request errors never echo URLs.
        data=self.request(request,self.settings.mojeek_api_url+'?'+urlencode(
            {'q':query,'fmt':'json','t':10,'api_key':self.settings.mojeek_api_key}),deadline)
        response=data.get('response')
        if not isinstance(response,dict) or response.get('status')!='OK':
            self.health.failure(503)
            raise ProviderError('Mojeek API reported an error; response details redacted.')
        if not isinstance(response.get('results'),list):raise ProviderError('Mojeek returned an invalid results array.')
        rows=[]
        for item in response['results'][:10]:
            if not isinstance(item,dict):continue
            published=None
            if type(item.get('pdate')) in (int,float):
                try:published=datetime.fromtimestamp(item['pdate'],timezone.utc).isoformat()
                except (ValueError,OverflowError,OSError):pass
            rows.append({'url':item.get('url'),'title':item.get('title'),'snippet':item.get('desc'),
                         'published_at':published,'source_query':query})
        return SourceBatch(rows)
