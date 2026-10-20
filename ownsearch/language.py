"""Language evidence with explicit script ambiguities; no topic dictionaries."""
import re
import unicodedata


def tag(value):
    if ',' in (value or ''):
        ranked=[]
        for position,item in enumerate(value.split(',')):
            parts=item.strip().split(';');quality=1.0
            for parameter in parts[1:]:
                if parameter.strip().startswith('q='):
                    try:quality=float(parameter.strip()[2:])
                    except ValueError:quality=0
            language=tag(parts[0])
            if language and 0<quality<=1:ranked.append((quality,-position,language))
        return max(ranked)[2] if ranked else None
    value=(value or '').split(';')[0].strip().lower().replace('_','-')
    return value if re.fullmatch(r'[a-z]{2,3}(?:-[a-z0-9]{2,8})*',value) else None


def identify(text, hint=None, allowed=None):
    names=[unicodedata.name(c,'') for c in text if c.isalpha()]
    counts={script:sum(script in n for n in names) for script in ['DEVANAGARI','GUJARATI','HIRAGANA','KATAKANA','HANGUL','CJK','THAI','ARABIC','LATIN']}
    script=max(counts,key=counts.get) if names and max(counts.values())>0 else 'UNKNOWN'
    choices={'DEVANAGARI':['hi','mr','ne'],'GUJARATI':['gu'],'HIRAGANA':['ja'],'KATAKANA':['ja'],
             'HANGUL':['ko'],'CJK':['zh','ja'],'THAI':['th'],'ARABIC':['ar','fa','ur'],'LATIN':['en']}.get(script,['und'])
    if counts['HIRAGANA']+counts['KATAKANA']:
        script,choices='KANA',['ja']
    prior=tag(hint)
    if prior and (script=='LATIN' or prior.split('-')[0] in choices):
        return {'language':prior,'script':script.lower(),'confidence':.9,'source':'explicit_prior','alternatives':choices}
    if allowed:
        configured=[x for x in choices if x in allowed]
        choices=configured or choices
    return {'language':choices[0], 'script':script.lower(), 'confidence':.95 if len(choices)==1 and script!='LATIN' else .4,
            'source':'script' if script!='LATIN' else 'default_prior','alternatives':choices}


def document_language(text,hint=None,detector='script',languages=('en','hi','gu')):
    evidence=identify(text,hint,languages)
    if detector!='lingua' or tag(hint):return evidence
    try:
        from lingua import IsoCode639_1, LanguageDetectorBuilder
        codes=[getattr(IsoCode639_1,code.upper()) for code in languages]
        engine=_detector(tuple(languages),tuple(codes),LanguageDetectorBuilder)
        result=engine.detect_language_of(text[:12000])
        if result:
            evidence.update(language=result.iso_code_639_1.name.lower(),source='lingua_configured',confidence=None)
    except (ImportError,AttributeError,ValueError) as exc:
        evidence['detector_unavailable']=type(exc).__name__
    return evidence

from functools import lru_cache
@lru_cache(maxsize=8)
def _detector(languages,codes,builder):
    return builder.from_iso_codes_639_1(*codes).build()
