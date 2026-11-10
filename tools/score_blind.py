"""本地人工盲评打分工具（只用标准库，不需要联网、不调用任何 API）。

用途：把 formal/blind_review/ratings.csv 里 296 条待评记录，做成一个"一张图 + 8 项检查"
的网页界面，点按钮即写回 CSV，避免手改 296 行表格。

启动：
    python score_blind.py
    浏览器打开 http://127.0.0.1:7861

说明：
    * 只显示匿名码 A/B/C/D，不显示它来自哪个模型（映射在 formal/private，本工具不读）。
    * 每点一次按钮立即落盘，中途关掉网页不丢数据。
    * 没有对应图片的匿名码（T03/T06/T08 的 C）自动跳过，不写 pass/fail。
"""
import argparse
import csv
import json
import os
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DEFAULT_FORMAL = Path(__file__).resolve().parent.parent / "formal"
COLS = ["task_id", "image_code", "check_id", "check_text",
        "human_status", "reason", "reviewer", "review_time"]
VALID = {"pass", "fail", "uncertain"}


class Store:
    def __init__(self, formal: Path, csv_path=None):
        self.formal = formal
        self.blind = formal / "blind_review"
        self.csv_path = Path(csv_path) if csv_path else self.blind / "ratings.csv"
        if not self.csv_path.exists():
            raise SystemExit(f"找不到评分表：{self.csv_path}")
        self.lock = threading.Lock()
        self.rows = []
        self.reload()

    def reload(self):
        with self.csv_path.open(encoding="utf-8-sig", newline="") as f:
            self.rows = [dict(r) for r in csv.DictReader(f)]
        for r in self.rows:
            for k in COLS:
                r.setdefault(k, "")

    def img_path(self, task, code):
        return self.blind / task / f"{code}.png"

    def has_img(self, task, code):
        return self.img_path(task, code).exists()

    def cards(self):
        seen = []
        for r in self.rows:
            key = (r["task_id"], r["image_code"])
            if key not in seen:
                seen.append(key)
        return [{"task_id": t, "code": c, "has_image": self.has_img(t, c)} for t, c in seen]

    def requirement(self, task):
        p = self.blind / task / "requirement.txt"
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    def titles(self):
        p = self.formal / "batch_input.json"
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return {c["task_id"]: c.get("title", "") for c in data.get("cases", [])}
        except Exception:
            return {}

    def state(self):
        with self.lock:
            scored = [r for r in self.rows
                      if r["human_status"] in VALID and self.has_img(r["task_id"], r["image_code"])]
            total = [r for r in self.rows if self.has_img(r["task_id"], r["image_code"])]
            per_task = {}
            for r in total:
                t = per_task.setdefault(r["task_id"], {"total": 0, "done": 0})
                t["total"] += 1
                if r["human_status"] in VALID:
                    t["done"] += 1
            return {
                "cards": self.cards(),
                "titles": self.titles(),
                "requirements": {t: self.requirement(t)
                                 for t in sorted({c["task_id"] for c in self.cards()})},
                "progress": {"done": len(scored), "total": len(total)},
                "per_task": per_task,
                "rows": [{"t": r["task_id"], "c": r["image_code"], "k": r["check_id"],
                          "text": r["check_text"], "s": r["human_status"],
                          "r": r["reason"], "by": r["reviewer"], "at": r["review_time"]}
                         for r in self.rows],
            }

    def save_card(self, task, code, reviewer, items):
        """items: {check_id: {"status":..., "reason":...}}"""
        stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        with self.lock:
            n = 0
            for r in self.rows:
                if r["task_id"] != task or r["image_code"] != code:
                    continue
                it = items.get(r["check_id"])
                if it is None:
                    continue
                status = (it.get("status") or "").strip()
                if status and status not in VALID:
                    raise ValueError(f"非法状态：{status}")
                if not status:
                    continue
                r["human_status"] = status
                r["reason"] = (it.get("reason") or "").strip().replace("\n", " ")
                r["reviewer"] = reviewer.strip()
                r["review_time"] = stamp
                n += 1
            tmp = self.csv_path.with_suffix(".csv.tmp")
            with tmp.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
                w.writeheader()
                w.writerows(self.rows)
            try:
                os.replace(tmp, self.csv_path)
            except PermissionError:
                raise RuntimeError(
                    "ratings.csv 被占用，写不进去。请先在 Excel 里关闭这个文件，再点一次按钮。")
        return n


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>人工盲评 · 逐项打分</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6eb;--ink:#1a1d23;--dim:#6b7280;
--pass:#15803d;--fail:#b91c1c;--unc:#b45309;--acc:#2563eb;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid var(--line);
padding:10px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:650}
.bar{flex:1;min-width:140px;height:8px;background:#eceef2;border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--acc);width:0;transition:width .2s}
.mono{font-variant-numeric:tabular-nums;color:var(--dim);font-size:13px}
input#rev{border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:13px;width:130px}
.wrap{max-width:1180px;margin:0 auto;padding:20px;display:grid;
grid-template-columns:minmax(320px,44%) 1fr;gap:20px;align-items:start}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.tag{display:inline-block;font-size:12px;color:var(--dim);letter-spacing:.04em}
.taskhead{font-weight:650;font-size:16px;margin:2px 0 8px}
.req{color:#374151;font-size:14px;background:#f9fafb;border-left:3px solid #d1d5db;
padding:10px 12px;border-radius:0 6px 6px 0;white-space:pre-wrap}
img.shot{width:100%;border-radius:8px;border:1px solid var(--line);display:block;
background:#fff;cursor:zoom-in}
img.zoom{position:fixed;inset:0;margin:auto;max-width:96vw;max-height:96vh;width:auto;
z-index:99;box-shadow:0 8px 40px rgba(0,0,0,.4);cursor:zoom-out;border:0;border-radius:0}
.noimg{padding:40px 12px;text-align:center;color:var(--dim);border:1px dashed var(--line);
border-radius:8px}
.check{border-top:1px solid var(--line);padding:10px 0;display:grid;
grid-template-columns:1fr auto;gap:8px 12px;align-items:start}
.check:first-of-type{border-top:0}
.check.focus{background:#f0f6ff;box-shadow:inset 3px 0 0 var(--acc)}
.q{font-size:14px}
.q b{color:var(--dim);font-weight:600;margin-right:6px;font-variant-numeric:tabular-nums}
.btns{display:flex;gap:6px}
button{font:inherit;font-size:13px;border:1px solid var(--line);background:#fff;
border-radius:6px;padding:4px 11px;cursor:pointer;color:#374151}
button:hover{border-color:#c7ccd4}
button.on[data-s=pass]{background:var(--pass);border-color:var(--pass);color:#fff}
button.on[data-s=fail]{background:var(--fail);border-color:var(--fail);color:#fff}
button.on[data-s=uncertain]{background:var(--unc);border-color:var(--unc);color:#fff}
textarea{grid-column:1/-1;width:100%;border:1px solid var(--line);border-radius:6px;
padding:6px 8px;font:13px/1.5 inherit;resize:vertical;min-height:34px;display:none}
textarea.show{display:block}
.foot{display:flex;justify-content:space-between;gap:10px;margin-top:14px}
.foot button{padding:7px 16px}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#111827;
color:#fff;padding:7px 14px;border-radius:6px;font-size:13px;opacity:0;
transition:opacity .25s;pointer-events:none;z-index:100}
#toast.on{opacity:.92}
.hint{color:var(--dim);font-size:12px;margin-top:6px}
</style></head><body>
<header>
  <h1>人工盲评</h1>
  <span class="mono" id="prog">0 / 0</span>
  <div class="bar"><i id="bar"></i></div>
  <label class="mono">评分员 <input id="rev" placeholder="你的名字" autocomplete="off"></label>
  <span class="mono" id="pos"></span>
</header>

<div class="wrap">
  <div class="panel">
    <span class="tag" id="tid">—</span>
    <div class="taskhead" id="tname">—</div>
    <div class="req" id="req"></div>
    <div class="hint">原始需求（评分时不要看别的图，也不要猜哪张来自哪个模型）</div>
  </div>
  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <div><span class="tag">当前图片</span> <b id="code" style="font-size:18px">—</b></div>
      <div class="mono" id="cardprog"></div>
    </div>
    <div id="shotbox"></div>
    <div id="checks" style="margin-top:12px"></div>
    <div class="foot">
      <button id="prev">← 上一张 (A)</button>
      <button id="next">下一张 → (D)</button>
    </div>
    <div class="hint">快捷键：<b>1</b> 通过 / <b>2</b> 不通过 / <b>3</b> 看不清 · <b>↑↓</b> 切换检查项 · <b>D</b> 下一张 · <b>A</b> 上一张</div>
  </div>
</div>
<div id="toast"></div>

<script>
let S=null, cards=[], idx=0, focusRow=0, cur={};
const $=s=>document.querySelector(s);

function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');
  clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove('on'),1100);}

async function boot(){
  S=await (await fetch('/api/state')).json();
  cards=S.cards;
  idx=0;
  // 跳到第一张"还有检查项没填"的图，实现断点续评
  const filledOf=(t,c)=>S.rows.filter(r=>r.t===t&&r.c===c&&['pass','fail','uncertain'].includes(r.s)).length;
  const first=cards.findIndex(c=>c.has_image && filledOf(c.task_id,c.code)<8);
  if(first>0) idx=first;
  render();
}

function render(){
  const c=cards[idx]; if(!c) return;
  cur={};
  S.rows.filter(r=>r.t===c.task_id&&r.c===c.code).forEach(r=>cur[r.k]=r);
  const reqText=S.requirements[c.task_id]||'';
  $('#tid').textContent='任务 '+c.task_id;
  $('#tname').textContent=(S.titles&&S.titles[c.task_id])||'';
  $('#req').textContent=reqText;
  $('#code').textContent=c.code;
  const box=$('#shotbox');
  if(c.has_image){
    box.innerHTML='<img class="shot" id="im" src="/img?t='+c.task_id+'&c='+c.code+'" alt="匿名图">';
    $('#im').onclick=e=>{e.target.classList.toggle('zoom')};
  } else {
    box.innerHTML='<div class="noimg">该匿名码没有对应图片<br><small>（该分支生成失败，整组留空，不填 pass/fail）</small></div>';
  }
  const keys=Object.keys(cur).sort();
  const filled=keys.filter(k=>['pass','fail','uncertain'].includes(cur[k].s)).length;
  $('#cardprog').textContent=filled+' / '+keys.length;
  $('#pos').textContent='第 '+(idx+1)+' / '+cards.length+' 张';
  const done=S.progress.done, tot=S.progress.total;
  $('#prog').textContent=done+' / '+tot;
  $('#bar').style.width=(tot?done/tot*100:0)+'%';

  $('#checks').innerHTML=keys.map((k,i)=>{
    const r=cur[k];
    const btns=['pass','fail','uncertain'].map(s=>{
      const label={pass:'通过',fail:'不通过',uncertain:'看不清'}[s];
      return '<button data-s="'+s+'" data-k="'+k+'" data-i="'+i+'" class="'+(r.s===s?'on':'')+'">'+label+'</button>';
    }).join('');
    const show=(r.s==='fail'||r.s==='uncertain')?' show':'';
    return '<div class="check'+(i===focusRow?' focus':'')+'" data-row="'+i+'">'
      +'<div class="q"><b>'+k+'</b>'+r.text+'</div>'
      +'<div class="btns">'+btns+'</div>'
      +'<textarea class="'+show.trim()+'" data-r="'+k+'" placeholder="写你实际看到的情况（不通过/看不清必填）">'
      +(r.r||'')+'</textarea></div>';
  }).join('');

  document.querySelectorAll('.btns button').forEach(b=>{
    b.onclick=()=>setStatus(b.dataset.k,b.dataset.s,+b.dataset.i);
  });
  document.querySelectorAll('textarea').forEach(t=>{
    t.oninput=()=>{cur[t.dataset.r].r=t.value;};
    t.onblur=()=>save();
  });
  document.querySelectorAll('.check').forEach(el=>{
    el.onclick=e=>{if(e.target.tagName==='BUTTON'||e.target.tagName==='TEXTAREA')return;
      focusRow=+el.dataset.row; paintFocus();};
  });
  if(focusRow>=keys.length) focusRow=0;
}

function paintFocus(){
  document.querySelectorAll('.check').forEach((el,i)=>el.classList.toggle('focus',i===focusRow));
}

async function setStatus(k,s,i){
  cur[k].s=s;
  const el=document.querySelector('button[data-k="'+k+'"][data-s="'+s+'"]');
  document.querySelectorAll('button[data-k="'+k+'"]').forEach(b=>b.classList.remove('on'));
  if(el) el.classList.add('on');
  const ta=document.querySelector('textarea[data-r="'+k+'"]');
  if(ta){ta.classList.toggle('show',s==='fail'||s==='uncertain');
    if(s==='fail'||s==='uncertain') ta.focus(); else {ta.value='';cur[k].r='';}}
  await save();
  if(s==='pass'){
    const total=Object.keys(cur).length;
    const from=(typeof i==='number'&&!isNaN(i))?i:focusRow;
    focusRow=Math.min(from+1,total-1); paintFocus();
  }
}

async function save(){
  const c=cards[idx]; if(!c||!c.has_image) return;
  const reviewer=$('#rev').value.trim()||'reviewer';
  const items={};
  Object.keys(cur).forEach(k=>{items[k]={status:cur[k].s,reason:cur[k].r||''}});
  const res=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task_id:c.task_id,image_code:c.code,reviewer:reviewer,items:items})});
  if(!res.ok){toast('保存失败：'+await res.text());return;}
  const d=await res.json();
  S.progress=d.progress; S.per_task=d.per_task;
  $('#prog').textContent=d.progress.done+' / '+d.progress.total;
  $('#bar').style.width=(d.progress.total?d.progress.done/d.progress.total*100:0)+'%';
  const filled=Object.keys(cur).filter(k=>['pass','fail','uncertain'].includes(cur[k].s)).length;
  $('#cardprog').textContent=filled+' / '+Object.keys(cur).length;
  localStorage.setItem('rev',$('#rev').value);
  toast('已保存');
}

function go(d){
  const n=idx+d;
  if(n<0||n>=cards.length){toast(d>0?'已经是最后一张':'已经是第一张');return;}
  save();               // 先落盘当前这张（含刚敲的理由），再切图
  idx=n; focusRow=0; render();
  window.scrollTo({top:0,behavior:'smooth'});
}

$('#next').onclick=()=>go(1);
$('#prev').onclick=()=>go(-1);
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT'){
    if(e.key==='Escape')e.target.blur();
    return;
  }
  const keys=Object.keys(cur).sort();
  if(e.key==='1'||e.key==='2'||e.key==='3'){
    const s={ '1':'pass','2':'fail','3':'uncertain' }[e.key];
    if(keys[focusRow]){e.preventDefault();setStatus(keys[focusRow],s,focusRow);}
  }
  if(e.key==='ArrowDown'){e.preventDefault();focusRow=Math.min(focusRow+1,keys.length-1);paintFocus();}
  if(e.key==='ArrowUp'){e.preventDefault();focusRow=Math.max(focusRow-1,0);paintFocus();}
  if(e.key==='d'||e.key==='D'){e.preventDefault();go(1);}
  if(e.key==='a'||e.key==='A'){e.preventDefault();go(-1);}
});
$('#rev').value=localStorage.getItem('rev')||'';
boot();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    store: Store = None

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._send(200, json.dumps(self.store.state(), ensure_ascii=False).encode())
        if u.path == "/img":
            t = (q.get("t") or [""])[0]
            c = (q.get("c") or [""])[0]
            p = self.store.img_path(t, c)
            if not p.exists():
                return self._send(404, b"missing")
            return self._send(200, p.read_bytes(), "image/png")
        return self._send(404, b"not found")

    def do_POST(self):
        if self.path != "/api/save":
            return self._send(404, b"not found")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            self.store.save_card(data["task_id"], data["image_code"],
                                 data.get("reviewer", ""), data.get("items", {}))
        except Exception as exc:
            return self._send(400, str(exc).encode())
        st = self.store.state()
        return self._send(200, json.dumps(
            {"progress": st["progress"], "per_task": st["per_task"]},
            ensure_ascii=False).encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal", default=str(DEFAULT_FORMAL))
    ap.add_argument("--csv", default=None,
                    help="评分表路径；第二名评分员请指向 ratings_r2.csv 之类的新文件，避免互相覆盖")
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    store = Store(Path(args.formal), args.csv)
    Handler.store = store
    st = store.state()
    print(f"评分表：{store.csv_path}")
    print(f"待评：{st['progress']['total']} 条（共 {len(st['cards'])} 张图，"
          f"{len(st['cards']) - sum(1 for c in st['cards'] if c['has_image'])} 个匿名码无图）")
    print(f"已完成：{st['progress']['done']} 条")
    print(f"请用浏览器打开： http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
