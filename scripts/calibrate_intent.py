#!/usr/bin/env python3
"""Choose a confidence-margin gate on held-out labeled TSV; never trains on these rows."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ownsearch.intent import get_model
from eval.run_eval import bootstrap

def calibrate(rows,model,target_precision=.9):
    observed=[]
    for expected,text in rows:
        predicted,probs=model.classify(text)
        values=sorted(probs.values(),reverse=True)
        margin=values[0]-(values[1] if len(values)>1 else 0) if values else 0
        observed.append((margin,predicted==expected))
    feasible=[]
    for threshold in sorted(set([0.0]+[m for m,_ in observed])):
        selected=[good for margin,good in observed if margin>=threshold]
        if selected and sum(selected)/len(selected)>=target_precision:feasible.append((len(selected),-threshold))
    threshold=-max(feasible)[1] if feasible else 1.0
    accepted=[good for margin,good in observed if margin>=threshold] if feasible else []
    return {'minimum_margin':threshold,'reject_all':not bool(feasible),'samples':len(rows),'coverage':len(accepted)/max(1,len(rows)),
        'accepted_accuracy':bootstrap(accepted),'accuracy_all':bootstrap([good for _,good in observed]),
        'scope':'calibration sample; evaluate separately on a disjoint test set'}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('heldout');p.add_argument('--output',required=True);p.add_argument('--data-dir');p.add_argument('--target-precision',type=float,default=.9);a=p.parse_args()
    rows=[tuple(line.split('\t',1)) for line in Path(a.heldout).read_text().splitlines() if line and not line.startswith('#')]
    result=calibrate(rows,get_model(a.data_dir),a.target_precision)
    Path(a.output).write_text(json.dumps({'en':result},indent=2))
if __name__=='__main__':main()
