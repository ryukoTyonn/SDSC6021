import json,hashlib,zipfile,collections,re,shutil
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
R=Path(__file__).resolve().parent
O=Path('/Users/maplelee/Documents/Codex/2026-11-08/vscode-2/outputs')
v=json.loads((R/'verification.json').read_text()); batch=json.loads((R/'batch_input.json').read_text()); manifests=[json.loads(p.read_text()) for p in sorted((R/'data').glob('*/manifest.json'))]
attempts=[a for m in manifests for a in m['attempts']]
audit=[json.loads(p.read_text()) for p in (R/'audit').glob('*.meta.json')]
assert len(audit)==len(attempts)==70
assert all(x['http_status']==200 for x in audit)
assert len(list((R/'data').glob('*/initial.png')))==10
votes=[];invalid=[];versions=collections.defaultdict(set)
for c,m in zip(batch['cases'],manifests):
 statuses={}
 versions['draw'].add(m['initial']['metadata']['model'])
 for role in ['gpt','gemini','deepseek']:
  b=R/'data'/c['task_id']/role
  raw=(b/'raw_response.txt').read_text(); raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
  f=json.loads(raw);statuses[role]={x['id']:x['status'] for x in f['checks']}
  if not f.get('revised_prompt'):invalid.append({'task_id':c['task_id'],'role':role,'reason':'revised_prompt empty','checks_retained':len(f['checks'])})
  assert len(f['checks'])==8
  assert len(f.get('priority_fixes',[]))<=2
  req=json.loads((b/'feedback_request.json').read_text())
  assert req['image_sha256']==hashlib.sha256((b.parent/'initial.png').read_bytes()).hexdigest()
  assert req['checklist']==c['checks']
  response=json.loads((b/'raw_response.response.json').read_text())
  versions[role].add(response.get('modelVersion',response.get('model','not reported')))
 for check in c['checks']:
  s={r:values[check['id']] for r,values in statuses.items()}
  if len(set(s.values()))>1:votes.append({'task_id':c['task_id'],'check_id':check['id'],'text':check['text'],'votes':s,'note':'failed branch uses last raw response; descriptive only'})
summary={'tasks':10,'complete_tasks':7,'images':37,'valid_feedback_and_prompts':27,'branches_with_raw_feedback':30,'requests':70,'draw_requests':sum(a['kind']=='draw' for a in attempts),'feedback_requests':sum(a['kind']=='feedback' for a in attempts),'failed_validation_attempts':6,'http_errors':0,'invalid_branches':invalid,'disagreements':votes,'returned_model_ids':{k:sorted(x) for k,x in versions.items()},'actual_sizes':sorted({tuple(s) for x in v for s in x['actual_sizes'].values()}),'configured_size':'1024x1024','wire_size_parameter':None,'cost':None,'cost_note':'provider pricing unavailable; use actual billing','random_control':False}
(R/'run_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));shutil.copy(R/'run_summary.json',O/'formal_run_summary.json')
lines=['# T01–T10 正式实验运行结果','', '本轮不含随机对照组；正式数据独立保存于桌面 genai_feedback/formal/data。', '', '完成 10 条用例的执行：7 条完整，3 条各缺少一个分支图。共 37 张图、27 份有效反馈与新提示词；30 个分支均保留原始反馈。','', '实际请求 70 次：37 次绘图、33 次反馈。全部 HTTP 200，其中 6 次反馈因空 revised_prompt 校验失败；无生图接口失败。三个分支各尝试两次后停止，没有静默替换图片。', '', '失败分支：T03/Gemini、T06/GPT、T08/Gemini。原始逐项判断仍在，但未据此补造新提示词或生成分支图。', '', '## 真实性与一致性核验','', '全部现有图片可解码；30 个分支初图哈希、需求、检查清单与对应初图一致。核心 app.py 与冻结压缩包相同。独立 HTTP 归档层保存全部请求体和响应，不保存鉴权头。开发集结果仍为 9 行，正式结果为 30 个分支记录。', '', '配置尺寸为 1024×1024，但冻结的 Gemini 生图请求没有发送尺寸参数，不能声称接口请求了该尺寸。实际尺寸：'+str(summary['actual_sizes'])+'。逐图尺寸和哈希见 formal/verification.json。', '', '配置模型 ID 见 freeze.json；服务端返回模型字段如下（转发接口的字段不能独立证明后端身份）：',json.dumps(summary['returned_model_ids'],ensure_ascii=False), '', '## 模型判断分歧','', '以下仅比较初图的模型判断，不代表人工真值。失败分支采用最后一次原始反馈，仅作描述性汇总。共 '+str(len(votes))+' 个检查项存在分歧。','']
for x in votes:lines.append('- '+x['task_id']+' '+x['check_id']+'：'+json.dumps(x['votes'],ensure_ascii=False))
lines+=['','## 下一步','', '先由人工对匿名图片包逐项盲评；缺失图片不评分，不填为 pass 或 fail。匿名映射保存在 formal/private，不放入盲评包。D01 C3、D03 C6/C8 人工复核字段仍保留，不并入正式统计。', '', '将空新提示词的处理约定作为下一版协议修订候选；本轮保留失败，不补跑、不混用规则。人工评分完成后再比较改进效果与模型判断准确性。费用须按服务商实际账单核实，未编造金额。']
(O/'正式实验运行报告.md').write_text('\n'.join(lines))
with zipfile.ZipFile(O/'formal_blind_review.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in (R/'blind_review').rglob('*'):
  if p.is_file():z.write(p,p.relative_to(R/'blind_review'))
images=sorted((R/'data').glob('*/initial.png'))
canvas=Image.new('RGB',(800,5*180),'white');pen=ImageDraw.Draw(canvas)
for i,p in enumerate(images):
 thumb=ImageOps.contain(Image.open(p).convert('RGB'),(390,150));x=(i%2)*400;y=(i//2)*180;canvas.paste(thumb,(x,y+22));pen.text((x+5,y+3),p.parent.name,fill='black')
canvas.save(O/'initial_images_overview.jpg')
print(json.dumps(summary,ensure_ascii=False,indent=2))
