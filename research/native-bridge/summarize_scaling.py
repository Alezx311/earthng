"""Summarize a scaling run without attributing the game's CPU to the bridge."""
import argparse
import collections
import json
from pathlib import Path
import statistics

def pct(values, q):
    values=sorted(values)
    return values[round((len(values)-1)*q)]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    a=p.parse_args()
    report=json.loads((a.run/'user/current/e2r_bridge/bench-scaling.json').read_text(encoding='utf8'))
    phases=collections.defaultdict(list)
    for line in (a.run/'cpu.jsonl').read_text(encoding='utf8').splitlines():
        row=json.loads(line); phases[row.get('phase','')].append(row)
    out={'queries':report['queries'],'reachable':report['reachable'],'lua_ms':report['luaMs'],'phases':[]}
    for transport in ('file','socket'):
        for g in report[transport]:
            phase=f"{transport}-{g['workers']}"; cpu=phases[phase]
            item={'phase':phase,'batches':len(g['rustMs']),'rust_ms_p50':pct(g['rustMs'],.5),
                  'roundtrip_ms_p50':pct(g['roundtripMs'],.5),'roundtrip_ms_p95':pct(g['roundtripMs'],.95),
                  'process_cpu_samples':len(cpu)}
            if g.get('cpuMs') and all(x < 1e12 for x in g['cpuMs']):
                item['worker_cpu_ms_sum']=sum(g['cpuMs'])
                item['worker_wall_ms_sum']=sum(g['rustMs'])
                item['worker_mean_active_cores']=sum(g['cpuMs'])/sum(g['rustMs']) if sum(g['rustMs']) else None
            if cpu:
                item['process_mean_logical_cores']=statistics.mean(s['process_cpu_one_core_pct'] for s in cpu)/100
                item['process_peak_logical_cores']=max(s['process_cpu_one_core_pct'] for s in cpu)/100
                item['process_peak_private_mib']=max(s['private_bytes'] for s in cpu)/2**20
            out['phases'].append(item)
    print(json.dumps(out,indent=2))

if __name__=='__main__': main()
