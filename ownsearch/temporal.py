"""Guarded calendar interpretation. No date parsing of bare ambiguous English words."""
import re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from .textproc import tokenize,normalize


def windows(text,language='en',timezone_name='UTC',now=None,holiday_country=''):
    try: zone=ZoneInfo(timezone_name or 'UTC')
    except (ZoneInfoNotFoundError,TypeError) as exc: raise ValueError('Invalid IANA timezone: '+str(timezone_name)) from exc   # invalid user timezones are explicit errors
    now=(now or datetime.now(timezone.utc)).astimezone(zone)
    words=tokenize(text); offsets=[]; cue=None; ambiguous=False
    for line in (Path(__file__).with_name('resources')/'calendar_days.tsv').read_text().splitlines():
        if line and not line.startswith('#'):
            offset, phrase=line.split('\t',1)
            if phrase in words: offsets=[int(offset)];cue=phrase;break
    if 'कल' in words:
        past={'था','थी','थे','हुआ','हुई'} & set(words)
        future={'होगा','होगी','होंगे','आएगा','आएगी'} & set(words)
        offsets=[-1] if past and not future else [1] if future and not past else [-1,1]
        ambiguous=len(offsets)>1;cue='कल'
    midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    parsed=None
    if offsets:
        # Parse the recognized phrase only, never the whole query. Calendar offsets
        # remain the deterministic fallback when a language pack is unavailable.
        try:
            import dateparser
            parsed=dateparser.parse(cue,languages=[language.split('-')[0]],settings={
                'RELATIVE_BASE':now,'TIMEZONE':str(zone),'RETURN_AS_TIMEZONE_AWARE':True})
        except (ImportError,ValueError): pass
        result=[{'after':(midnight+timedelta(days=o)).timestamp(),
                 'before':(midnight+timedelta(days=o+1)).timestamp()-.001} for o in offsets]
        return {'windows':result,'timezone':str(zone),'ambiguous':ambiguous,'cue':cue,
                'parser':'dateparser+calendar' if parsed else 'calendar',
                'note':'The day can mean yesterday or tomorrow; both windows are searched.' if ambiguous else None}
    # ISO dates and month/day/year forms require a numeric anchor. Bare May,
    # March, sat and second never trigger the date library.
    match=re.search(r'\b\d{4}-\d{1,2}-\d{1,2}\b',normalize(text).folded)
    if match:
        try:
            stamp=datetime.fromisoformat(match.group()).replace(tzinfo=zone)
            return {'windows':[{'after':stamp.timestamp(),'before':(stamp+timedelta(days=1)).timestamp()-.001}],
                    'timezone':str(zone),'ambiguous':False,'cue':match.group(),'parser':'iso_calendar'}
        except ValueError: pass
    if holiday_country:
        cues=[]
        for line in (Path(__file__).with_name('resources')/'holiday_cues.tsv').read_text().splitlines():
            if line and not line.startswith('#'): cues.append(line.split('\t',1)[1])
        if set(words)&set(cues):
            try:
                import holidays
                year=next((int(w) for w in words if w.isascii() and w.isdigit() and len(w)==4),now.year)
                calendar=holidays.country_holidays(holiday_country,years=[year],language=language)
                matched=[]
                for day,name in calendar.items():
                    aliases=[tokenize(v) for v in re.split(r'[()/;,]',name)]
                    if any(a and set(a)<=set(words) for a in aliases):
                        begin=datetime.combine(day,datetime.min.time(),tzinfo=zone)
                        matched.append({'after':begin.timestamp(),'before':(begin+timedelta(days=1)).timestamp()-.001})
                if matched:return {'windows':matched,'timezone':str(zone),'ambiguous':len(matched)>1,'parser':'holidays','country':holiday_country}
            except (ImportError,ValueError,NotImplementedError):pass
    return {'windows':[],'timezone':str(zone),'ambiguous':False}
