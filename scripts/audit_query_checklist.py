#!/usr/bin/env python3
"""Audit category coverage on an existing index; unlabeled coverage is never accuracy."""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ownsearch.config import Settings
from ownsearch.engine import SearchEngine


def read_checklist(path):
    if Path(path).suffix == '.json':
        return json.loads(Path(path).read_text())
    category, cases = None, []
    for line in Path(path).read_text().splitlines():
        match = re.fullmatch(r"Category (\d+): (.+)", line.strip())
        if match:
            category = match[2]
        match = re.fullmatch(r"(\d+)\. (.+)", line.strip())
        if match and category:
            cases.append({"number": int(match[1]), "category": category, "query": match[2]})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checklist', default=str(Path(__file__).resolve().parents[1] / 'tests/fixtures/daily_search_checklist.json'))
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--judgments-output', help='write a separate review template for relevance judgments')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    settings = Settings.load(args.data_dir, log_queries=False, user_agent=Settings().user_agent)
    engine = SearchEngine(settings=settings)
    categories = defaultdict(lambda: {"queries": 0, "nonempty": 0, "low_confidence": 0})
    rows = []
    for case in read_checklist(args.checklist):
        result = engine.search(case['query'], limit=5, live=args.live, use_cache=False)
        stats = categories[case['category']]
        stats['queries'] += 1
        stats['nonempty'] += bool(result['results'])
        stats['low_confidence'] += bool(result['coverage']['low_confidence'])
        rows.append({**case, "judgments": {}, "review_status": "unreviewed", "result": result})
    report = {"queries": len(rows), "live": args.live, "categories": dict(categories),
              "accuracy": None, "accuracy_note": "Human relevance and answer judgments are required. Nonempty results and confidence are not accuracy.",
              "runs": rows}
    Path(args.output).write_text(json.dumps(report, indent=2))
    if args.judgments_output:
        template = {'description':'Fill judgments with reviewed URL grades 0–3, then set review_status to reviewed. Empty unreviewed cases are not accuracy measurements.',
                    'queries':[{**case,'judgments':{},'review_status':'unreviewed'} for case in read_checklist(args.checklist)]}
        Path(args.judgments_output).write_text(json.dumps(template, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
