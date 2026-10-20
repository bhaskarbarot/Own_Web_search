#!/usr/bin/env python3
"""Independently compare emitted prices/statistics to captured primary chart responses."""
import argparse,json,math,sqlite3,statistics
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path

def validate(runs,cache_path):
    connection=sqlite3.connect('file:'+str(Path(cache_path).resolve())+'?mode=ro',uri=True)
    records=[]
    for row in connection.execute('SELECT value FROM responses'):
        result=json.loads(row[0]).get('chart',{}).get('result') or []
        records.extend(result)
    connection.close();report=[]
    for run in runs:
        answer=run.get('answer') or {};kind=answer.get('type')
        if kind not in ('stock_quote','stock_history'):continue
        symbol=answer['symbol'];sources=[r for r in records if r.get('meta',{}).get('symbol')==symbol]
        if not sources:
            report.append({'symbol':symbol,'status':'unverified','reason':'no captured source response'});continue
        raw=max(sources,key=lambda value:len(value.get('timestamp',[])));meta=raw['meta'];checks={}
        checks['currency']=answer['currency']==meta.get('currency')
        stamp=datetime.fromisoformat(answer['as_of']).timestamp()
        checks['not_future']=stamp<=datetime.now(timezone.utc).timestamp()+300
        checks['disclaimer_present']=bool(answer.get('disclaimer'))
        if kind=='stock_quote':
            checks['price']=math.isclose(answer['price'],meta['regularMarketPrice'],abs_tol=1e-8)
            checks['timestamp']=abs(stamp-meta['regularMarketTime'])<1
        else:
            zone=ZoneInfo(answer.get('exchange_timezone') or 'UTC');analysis=answer['analysis']
            prices=raw['indicators'].get('adjclose',[{}])[0].get('adjclose') or raw['indicators']['quote'][0]['close']
            records_by_day={datetime.fromtimestamp(t,zone).date().isoformat():value for t,value in zip(raw['timestamp'],prices) if isinstance(value,(int,float)) and math.isfinite(value) and value>0}
            emitted=answer['series'];selected=[records_by_day.get(day) for day,_ in emitted]
            checks['series_matches_source']=all(source is not None and abs(source-price)<.00006 for source,(_,price) in zip(selected,emitted))
            if not checks['series_matches_source']:
                report.append({'symbol':symbol,'status':'failed','checks':checks});continue
            first,last=selected[0],selected[-1]
            calculated={'change':last-first,'change_pct':100*(last/first-1),'mean':math.fsum(selected)/len(selected),
                        'sma20':math.fsum(selected[-20:])/20 if len(selected)>=20 else None,
                        'sma50':math.fsum(selected[-50:])/50 if len(selected)>=50 else None}
            running=selected[0];drawdowns=[]
            for value in selected:
                running=max(running,value);drawdowns.append(100*(value/running-1))
            calculated['max_drawdown_pct']=min(drawdowns)
            days={day for day,_ in emitted};returns=[]
            for i in range(1,len(prices)):
                prior,current=prices[i-1],prices[i]
                prior_day=datetime.fromtimestamp(raw['timestamp'][i-1],zone).date().isoformat()
                current_day=datetime.fromtimestamp(raw['timestamp'][i],zone).date().isoformat()
                if prior_day in days and current_day in days and prior and current and prior>0 and current>0:returns.append(math.log(current)-math.log(prior))
            calculated['volatility_pct']=statistics.pstdev(returns)*math.sqrt(252)*100 if len(returns)>2 else 0
            for name,value in calculated.items():checks[name]=value is None and analysis.get(name) is None or value is not None and math.isclose(value,analysis[name],abs_tol=1e-6)
            checks['date_bounds']=emitted[0][0]==analysis['start'][0] and emitted[-1][0]==analysis['end'][0]
            checks['chronological']=all(a[0]<b[0] for a,b in zip(emitted,emitted[1:]))
        report.append({'symbol':symbol,'type':kind,'status':'passed' if all(checks.values()) else 'failed','checks':checks,
                       'scope':'Primary-feed consistency and arithmetic; not independent-provider or investment validation.'})
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',required=True);p.add_argument('--cache',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    results=validate(json.loads(Path(a.runs).read_text())['runs'],a.cache)
    Path(a.output).write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
