"""Optional keyed general indexes. No accounts, keys or charges are provisioned."""
from urllib.parse import urlencode
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
