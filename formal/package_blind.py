"""Blind only image labels; no random control generation or API calls."""
import csv,json,hashlib,random,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
out=ROOT/'blind_review';out.mkdir(exist_ok=True)
private=ROOT/'private';private.mkdir(exist_ok=True)
mapfile=private/'blind_mapping.json'
if mapfile.exists(): raise RuntimeError('Mapping exists; refusing to relabel')
mapping=[];rng=random.SystemRandom()
for c in json.loads((ROOT/'batch_input.json').read_text())['cases']:
 task=c['task_id'];sources=['initial','gpt','gemini','deepseek'];rng.shuffle(sources)
 dest=out/task;dest.mkdir(exist_ok=True)
 for label,source in zip('ABCD',sources):
  f=ROOT/'data'/task/('initial.png' if source=='initial' else source+'/result.png')
  if not f.exists():continue
  shutil.copyfile(f,dest/(label+'.png'))
  mapping.append({'task_id':task,'image_code':label,'source':source,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
 (dest/'requirement.txt').write_text(c['original_requirement'])
mapfile.write_text(json.dumps(mapping,ensure_ascii=False,indent=2))
shutil.copyfile(ROOT/'blind_review_template.csv',out/'ratings.csv')
print('Blind images:',len(mapping))
