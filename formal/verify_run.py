import json, hashlib
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parent
batch=json.loads((ROOT/'batch_input.json').read_text())
report=[]
for c in batch['cases']:
 d=ROOT/'data'/c['task_id']; errors=[]; sizes={}; disagreements=[]
 if not (d/'manifest.json').exists():
  report.append({'task_id':c['task_id'],'complete':False,'errors':['not started']});continue
 m=json.loads((d/'manifest.json').read_text()); statuses={}
 initial=d/'initial.png'; sha=hashlib.sha256(initial.read_bytes()).hexdigest() if initial.exists() else None
 for role,file in [('initial',initial)]+[(r,d/r/'result.png') for r in ['gpt','gemini','deepseek']]:
  if file.exists():
   with Image.open(file) as im: sizes[role]=list(im.size);im.verify()
  else: errors.append(role+': missing image')
 for role in ['gpt','gemini','deepseek']:
  b=d/role
  try:
   request=json.loads((b/'feedback_request.json').read_text()); feedback=json.loads((b/'feedback.json').read_text())
   assert request['image_sha256']==sha and request['checklist']==c['checks'] and request['original_requirement']==c['original_requirement']
   assert [x['id'] for x in feedback['checks']]==[x['id'] for x in c['checks']]
   assert (b/'revised_prompt.txt').read_text()==feedback['revised_prompt']
   statuses[role]={x['id']:x['status'] for x in feedback['checks']}
   for f in ['raw_response.txt','raw_response.response.json','draw_response.json']:
    if not (b/f).exists(): errors.append(role+': missing '+f)
  except Exception as exc: errors.append(role+': '+repr(exc))
 for check in c['checks']:
  votes={r:s.get(check['id']) for r,s in statuses.items()}
  if len(set(votes.values()))>1: disagreements.append({'check_id':check['id'],'text':check['text'],'votes':votes})
 report.append({'task_id':c['task_id'],'complete':not errors and bool(m.get('finished_at')),'errors':errors,'configured_size':c['requested_image_size'],'wire_size_parameter':None,'actual_sizes':sizes,'initial_sha256':sha,'attempts':len(m['attempts']),'failed_attempts':[a for a in m['attempts'] if a.get('success') is False],'disagreements':disagreements})
(ROOT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'complete':sum(x['complete'] for x in report),'images':sum(len(x.get('actual_sizes',{})) for x in report),'attempts':sum(x.get('attempts',0) for x in report),'failed_attempts':sum(len(x.get('failed_attempts',[])) for x in report)},ensure_ascii=False))
