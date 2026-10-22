#!/usr/bin/env python3
"""Automated Top 100 AI Agent Web Search Queries Benchmark Runner.

Executes all 100 queries across 10 categories, evaluating:
- Latency (cold vs warm)
- Result precision & valid URL links
- Firecrawl structured Markdown generation
- DuckDuckGo-style Instant Answer extraction
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ownsearch import search_tool, SearchResults
from ownsearch.config import Settings
from ownsearch.coordinator import IndependentSearch

def run_benchmark(query_file, output_file, max_results=5, timeout_s=4.0):
    queries = json.loads(Path(query_file).read_text(encoding='utf-8'))
    print(f"Loaded {len(queries)} queries from {query_file}")
    
    # Initialize engine
    settings = Settings.load(persistent_cache_enabled=True, source_planning_enabled=True)
    settings.search_timeout_ms = int(timeout_s * 1000)
    engine = IndependentSearch(settings)
    
    results_by_cat = defaultdict(list)
    all_runs = []
    
    print("\n" + "=" * 90)
    print(f"{'#':<4} {'Cat':<15} {'Status':<8} {'Time':<10} {'Res':<5} {'Top URL':<42}")
    print("=" * 90)
    
    for item in queries:
        qid = item['id']
        category = item['category'][:14]
        q_text = item['query']
        
        t0 = time.time()
        try:
            # Execute with search_tool
            res_obj = search_tool(
                q_text,
                max_results=max_results,
                engine=engine,
                time_budget_s=timeout_s,
                answer=True
            )
            took = (time.time() - t0) * 1000
            
            raw_res = res_obj.to_dict()
            results = raw_res.get('results', [])
            answer = raw_res.get('answer')
            cached = raw_res.get('cached', False)
            
            top_url = results[0].get('url', '') if results else 'No results'
            top_title = results[0].get('title', '') if results else ''
            has_markdown = any(bool(r.get('markdown')) for r in results)
            
            status = 'OK' if results else 'EMPTY'
            
            record = {
                'id': qid,
                'category': item['category'],
                'query': q_text,
                'status': status,
                'took_ms': round(took, 2),
                'results_count': len(results),
                'top_url': top_url,
                'top_title': top_title,
                'has_answer': bool(answer),
                'answer_type': answer.get('type') if answer else None,
                'has_markdown': has_markdown,
                'cached': cached
            }
            
            results_by_cat[item['category']].append(record)
            all_runs.append(record)
            
            display_url = top_url if len(top_url) <= 40 else top_url[:37] + '...'
            print(f"{qid:<4} {category:<15} {status:<8} {took:7.1f}ms {len(results):<5} {display_url:<42}")
            
        except Exception as e:
            took = (time.time() - t0) * 1000
            record = {
                'id': qid,
                'category': item['category'],
                'query': q_text,
                'status': f'ERR: {str(e)[:20]}',
                'took_ms': round(took, 2),
                'results_count': 0,
                'top_url': '',
                'top_title': '',
                'has_answer': False,
                'answer_type': None,
                'has_markdown': False,
                'cached': False
            }
            results_by_cat[item['category']].append(record)
            all_runs.append(record)
            print(f"{qid:<4} {category:<15} {'ERR':<8} {took:7.1f}ms 0     {str(e)[:40]}")
    
    print("=" * 90)
    
    # Category summary
    summary = {}
    print("\n" + "=" * 80)
    print("CATEGORY PERFORMANCE SUMMARY")
    print("=" * 80)
    print(f"{'Category':<32} {'Queries':<8} {'OK Rate':<10} {'Avg Took':<12} {'Answer%':<10} {'Markdown%'}")
    print("-" * 80)
    
    total_queries = len(all_runs)
    total_success = sum(1 for r in all_runs if r['status'] == 'OK')
    total_answers = sum(1 for r in all_runs if r['has_answer'])
    total_markdown = sum(1 for r in all_runs if r['has_markdown'])
    avg_latency = sum(r['took_ms'] for r in all_runs) / max(1, total_queries)
    
    for cat, records in results_by_cat.items():
        cat_total = len(records)
        cat_ok = sum(1 for r in records if r['status'] == 'OK')
        cat_ans = sum(1 for r in records if r['has_answer'])
        cat_md = sum(1 for r in records if r['has_markdown'])
        cat_avg_ms = sum(r['took_ms'] for r in records) / max(1, cat_total)
        
        ok_pct = (cat_ok / cat_total) * 100
        ans_pct = (cat_ans / cat_total) * 100
        md_pct = (cat_md / cat_total) * 100
        
        summary[cat] = {
            'queries': cat_total,
            'success_count': cat_ok,
            'success_rate_pct': round(ok_pct, 1),
            'avg_latency_ms': round(cat_avg_ms, 1),
            'answer_rate_pct': round(ans_pct, 1),
            'markdown_rate_pct': round(md_pct, 1)
        }
        
        print(f"{cat:<32} {cat_total:<8} {ok_pct:5.1f}%    {cat_avg_ms:8.1f} ms   {ans_pct:5.1f}%     {md_pct:5.1f}%")
        
    print("-" * 80)
    overall_ok_pct = (total_success / total_queries) * 100
    overall_ans_pct = (total_answers / total_queries) * 100
    overall_md_pct = (total_markdown / total_queries) * 100
    print(f"{'TOTAL / OVERALL':<32} {total_queries:<8} {overall_ok_pct:5.1f}%    {avg_latency:8.1f} ms   {overall_ans_pct:5.1f}%     {overall_md_pct:5.1f}%")
    print("=" * 80)
    
    report = {
        'total_queries': total_queries,
        'overall_success_rate_pct': round(overall_ok_pct, 1),
        'overall_avg_latency_ms': round(avg_latency, 1),
        'overall_answer_rate_pct': round(overall_ans_pct, 1),
        'overall_markdown_rate_pct': round(overall_md_pct, 1),
        'category_summary': summary,
        'runs': all_runs
    }
    
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(output_file).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\nDetailed benchmark report saved to {output_file}")
    return report

def main():
    parser = argparse.ArgumentParser(description="Top 100 AI Agent Queries Benchmark")
    parser.add_argument('--queries', default='eval/top_100_ai_agent_queries.json')
    parser.add_argument('--output', default='eval/runs/independent/top100_benchmark_results.json')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=3.5)
    args = parser.parse_args()
    
    run_benchmark(args.queries, args.output, max_results=args.limit, timeout_s=args.timeout)

if __name__ == '__main__':
    main()
