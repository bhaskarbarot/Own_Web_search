"""Local multilingual Wikidata label index. Imports are streamed; no bundled topic catalog."""
import json
from pathlib import Path
from .db import Database
from .textproc import exact_tokens, normalize, ALL_STOPWORDS, stem
from .transliterate import romanize

TYPES={'COMPANY','PERSON','LOCATION','PRODUCT','LANG','ENTITY'}

class EntityIndex:
    def __init__(self, data_dir):
        self.db=Database(Path(data_dir)/'entities.db', '''
          CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, record TEXT NOT NULL);
          CREATE VIRTUAL TABLE IF NOT EXISTS labels USING fts5(id UNINDEXED,name,lang UNINDEXED, tokenize='unicode61 remove_diacritics 0');
          CREATE TABLE IF NOT EXISTS provenance(key TEXT PRIMARY KEY,value TEXT);
        ''')

    def import_records(self, records, source='user import', limit=None):
        count=0
        for record in records:
            qid=record.get('id','')
            if not qid.startswith('Q') or not qid[1:].isdigit(): continue
            labels=[]
            for lang, value in record.get('labels',{}).items():
                if value.get('value'): labels.append((qid,value['value'],lang))
            for lang, values in record.get('aliases',{}).items():
                labels.extend((qid,v['value'],lang) for v in values if v.get('value'))
            labels += [(qid,romanize(name),lang+'-Latn') for _,name,lang in list(labels) if not name.isascii()]
            with self.db.tx() as c:
                c.execute('INSERT OR REPLACE INTO entities VALUES(?,?)',(qid,json.dumps(record,ensure_ascii=False)))
                c.execute('DELETE FROM labels WHERE id=?',(qid,))
                c.executemany('INSERT INTO labels(id,name,lang) VALUES(?,?,?)',sorted(set(labels)))
            count+=1
            if limit and count>=limit: break
        with self.db.tx() as c:
            c.execute('INSERT OR REPLACE INTO provenance VALUES(?,?)',('source',source))
        return count

    def import_cache(self,path,limit=1000):
        import sqlite3
        path=Path(path)
        if not path.exists():return 0
        connection=sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True)
        try:
            exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'").fetchone()
            if not exists:return 0
            seen=set()
            def records():
                for qid,value in connection.execute('SELECT qid,value FROM records ORDER BY full DESC,ts DESC LIMIT ?',(max(1,limit)*2,)):
                    if qid in seen:continue
                    seen.add(qid);record=json.loads(value);record.setdefault('id',qid);yield record
            return self.import_records(records(),source='existing cached Wikidata records',limit=limit)
        finally:connection.close()

    def link(self,text,language='en',limit=3):
        from .knowledge import Entity
        tokens=exact_tokens(text)
        if not tokens: return []
        terms=' OR '.join('"'+t.replace('"','""')+'"' for t in dict.fromkeys(tokens))
        rows=self.db.query('SELECT id,name,lang FROM labels WHERE labels MATCH ? ORDER BY bm25(labels) LIMIT 150',(terms,))
        matches={}
        for row in rows:
            name=exact_tokens(row['name'])
            if len(name)==1 and name[0] in ALL_STOPWORDS and tokens!=name:continue
            if name and any(tokens[i:i+len(name)]==name for i in range(len(tokens)-len(name)+1)):
                matches.setdefault(tuple(name),set()).add(row['id'])
        entities=[]; used=set();blocked=set();records={}
        def record_for(qid):
            if qid not in records:records[qid]=json.loads(self.db.one('SELECT record FROM entities WHERE id=?',(qid,))[0])
            return records[qid]
        try:properties=json.loads((Path(self.db.path).parent/'wikidata_properties.json').read_text())
        except (OSError,ValueError):properties={}
        context={stem(w) for w in tokens if w not in ALL_STOPWORDS}
        context_expansions=set()
        for match,identities in matches.items():
            if len(identities)==1:
                rec=record_for(next(iter(identities)))
                context_expansions.update(stem(w) for v in rec.get('labels',{}).values() for w in exact_tokens(v.get('value','')))
        def relevance(qid,name):
            rec=record_for(qid);remaining=context-{stem(w) for w in name}
            desc=' '.join(v.get('value','') for v in rec.get('descriptions',{}).values())
            words={stem(w) for w in exact_tokens(desc)}
            props=' '.join(' '.join([properties.get(pid,{}).get('label','')]+properties.get(pid,{}).get('aliases',[])) for pid in rec.get('claims',{}))
            return len((remaining|context_expansions)&words)+2*len(remaining&{stem(w) for w in exact_tokens(props)})
        for name, ids in sorted(matches.items(),key=lambda item:-len(item[0])):
            if set(name)&(used|blocked):continue
            if len(ids)>1:
                ranked=sorted(((relevance(qid,name),qid) for qid in ids),reverse=True)
                if ranked[0][0]<=0 or ranked[0][0]==ranked[1][0]:
                    if len(name)>1:blocked.update(name)
                    continue
                ids={ranked[0][1]}
            qid=next(iter(ids)); record=record_for(qid)
            labels=record.get('labels',{}); aliases=record.get('aliases',{})
            lang=language.split('-')[0]
            label=(labels.get(lang) or labels.get('en') or next(iter(labels.values()),{})).get('value','')
            names=[v['value'] for code,v in labels.items() if code in (lang,'en') and v.get('value')]
            names += [v['value'] for code,values in aliases.items() if code in (lang,'en') for v in values if v.get('value')]
            names=list(dict.fromkeys([' '.join(name)]+names))[:64]
            e=Entity(qid,label,(record.get('descriptions',{}).get(lang) or record.get('descriptions',{}).get('en') or {}).get('value',''),names,' '.join(name),1.0)
            e.wiki_title=((record.get('sitelinks') or {}).get('enwiki') or {}).get('title')
            e.entity_type=record.get('entity_type','ENTITY') if record.get('entity_type') in TYPES else 'ENTITY'
            # URL values carry source roles through the existing knowledge helper when requested.
            e.claims=record.get('claims',{})
            entities.append(e); used.update(name)
            if len(entities)>=limit: break
        return entities


def mask(text, entities=()):
    """The same typed substitution is used for labeled training text and live text."""
    words=exact_tokens(text)
    for e in sorted(entities,key=lambda e:-len(exact_tokens(e.span))):
        span=exact_tokens(e.span); typ=getattr(e,'entity_type','ENTITY')
        if typ not in TYPES:typ='ENTITY'
        i=0
        while span and i<=len(words)-len(span):
            if words[i:i+len(span)]==span:
                words[i:i+len(span)]=['__'+typ+'__']; i+=1
            else:i+=1
    return ' '.join(words)


def json_records(path):
    """Accept a JSONL export or a line-oriented Wikidata JSON array dump."""
    import gzip
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            line=line.strip().rstrip(',')
            if line and line not in ('[',']'):
                yield json.loads(line)
