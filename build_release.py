#!/usr/bin/env python3
from pathlib import Path
import argparse,json
from bosfor.release import build_release

p=argparse.ArgumentParser(description='Build a secret-free Bosfor Restaurant OS release ZIP')
p.add_argument('output',nargs='?',default='dist/bosfor-restaurant-os-production.zip')
a=p.parse_args()
root=Path(__file__).resolve().parent
manifest=build_release(root,root/a.output)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
