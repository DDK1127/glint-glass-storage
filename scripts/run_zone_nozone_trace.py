import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from glass_sim.zone_nozone_comparison import load_config
from glass_sim.zone_nozone_trace import run

if __name__=="__main__":
    p=argparse.ArgumentParser()
    default_config=ROOT/"experiments/zone-nozone-comparison/full.json"
    p.add_argument("--config",type=Path,default=default_config)
    p.add_argument("--smoke",action="store_true",help="One placement seed at 16 m; keep the full natural trace")
    p.add_argument("--workers",type=int,default=1)
    args=p.parse_args()
    c=load_config(args.config)
    if Path(args.config).resolve()==default_config.resolve():
        c=replace(c,output_dir=ROOT/"results/zone-nozone-natural-arrivals")
    if args.smoke:
        c=replace(c,seeds=c.seeds[:1],lengths_m=(16,),output_dir=ROOT/"results/smoke-zone-nozone-natural-arrivals")
    run(c,workers=args.workers)
