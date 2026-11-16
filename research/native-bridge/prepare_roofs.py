"""Extract bounded 3D building footprints from the local Kyiv reference fixture."""
import argparse
import gzip
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists(): raise SystemExit('Refusing to overwrite')
    with gzip.open(a.fixture,'rt',encoding='utf8') as f: d=json.load(f)
    i,j=d['tile']['i'],d['tile']['j']
    result={'source':f'Kyiv fixture tile {i},{j}; one offline cell', 'rect':[500*i,500*j,500*(i+1),500*(j+1)],
            'polygons':[b['rings'] for b in d['cell']['buildings']]}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print(f"{len(result['polygons'])} footprints -> {a.out}")
if __name__=='__main__':main()
