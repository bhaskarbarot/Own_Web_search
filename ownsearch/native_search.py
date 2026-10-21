"""Discover semantic HTML search controls and construct same-origin safe GETs.

No endpoint or parameter name is guessed. HTML form semantics follow WHATWG:
https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#form-submission
Search forms remain subject to robots, scope and the normal fetch budgets.
"""
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from .util import origin_of
from .webmodels import web_url

# Outbound dependency policy from goal.md Section 4. This is an exclusion policy,
# never a relevance, topic, answer, preferred-domain or expected-result mapping.
SEARCH_SERVICES = frozenset(('google','bing','brave','duckduckgo','searx','searxng',
                             'mojeek','marginalia','yahoo','startpage','yandex',
                             'tavily','serper','serpapi'))


def independent_url(url, allow_private=False):
    url=web_url(url,allow_private)
    if not url:
        return None
    if SEARCH_SERVICES.intersection((urlsplit(url).hostname or '').lower().split('.')):
        return None
    return url

class SearchForms(HTMLParser):
    def __init__(self,url,allow_private=False):
        super().__init__(convert_charrefs=True)
        self.url,self.base,self.allow_private=url,url,allow_private
        self.forms=[];self.current=None;self.base_set=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='base' and not self.base_set and a.get('href'):
            self.base=urljoin(self.url,a['href']);self.base_set=True
        if tag=='form':
            if self.current is not None:
                self.current['invalid']=True
                return
            self.current={'action':urljoin(self.base,a.get('action') or self.url),
                          'method':(a.get('method') or 'get').lower(),
                          'role':(a.get('role') or '').lower(), 'inputs':[], 'invalid':False}
        elif self.current is not None and tag=='input':
            if 'disabled' not in a:
                self.current['inputs'].append({'name':a.get('name') or '',
                    'type':(a.get('type') or 'text').lower(),'role':(a.get('role') or '').lower(),
                    'value':a.get('value') or ''})
                if len(self.current['inputs'])>32:self.current['invalid']=True
        elif self.current is not None and tag=='button':
            if a.get('formaction') or a.get('formmethod'):
                self.current['invalid']=True
    def handle_endtag(self,tag):
        if tag!='form' or self.current is None:return
        form,self.current=self.current,None
        if form['invalid'] or form['method']!='get':return
        if any(i['type'] in ('password','file') for i in form['inputs']):return
        fields=[i for i in form['inputs'] if i['name'] and (i['type']=='search' or i['role']=='searchbox'
                 or (form['role']=='search' and i['type']=='text'))]
        if len(fields)!=1:return
        action=independent_url(form['action'],self.allow_private)
        if not action or origin_of(action)!=origin_of(self.url):return
        selected=fields[0]
        fields=[(i['name'],i['value'],i is selected) for i in form['inputs']
                if i['name'] and (i['type']=='hidden' or i is selected)]
        row={'action':action,'fields':fields}
        if row not in self.forms and len(self.forms)<4:self.forms.append(row)


def discover_search_forms(html,url,allow_private=False):
    parser=SearchForms(url,allow_private)
    parser.feed(html)
    return parser.forms


def submit_search_url(form,query,allow_private=False):
    if not isinstance(query,str) or not query.strip() or len(query)>1000:return None
    action=independent_url(form.get('action'),allow_private)
    if not action:return None
    # Successful controls are in document order, preserving duplicate names.
    pairs=[]
    for name,value,is_query in form.get('fields',[]):
        pairs.append((name,query if is_query else value))
    if not any(field[2] for field in form.get('fields',[])):return None
    p=urlsplit(action)
    # A GET submission replaces the action's query according to HTML form rules.
    return independent_url(urlunsplit((p.scheme,p.netloc,p.path,urlencode(pairs),'')),allow_private)
