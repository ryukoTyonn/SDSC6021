import argparse, base64, csv, hashlib, io, json, os, re, time, uuid
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from urllib import request, error

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None

BRANCHES = {'gpt': 'gpt6.0sol', 'gemini': 'gemini-3.8-flash', 'deepseek': 'deepseek-v4-pro'}
DRAW = 'deepseek-v4.1-flash'
SYSTEM = 'Inspect the actual image against every checklist item. Return JSON only: checks [{id,status,evidence}], priority_fixes [string], revised_prompt string. status must be pass, fail, or uncertain. Include at most two priority fixes. If all requirements pass, do not invent problems. Preserve all original requirements. Do not invent visual evidence.'

class ApiError(Exception): pass

def configured(value):
    return bool(value) and 'YOUR_' not in value

def config(role):
    prefix = 'DRAW' if role == 'draw' else role.upper()
    return {'base': os.getenv(prefix+'_BASE_URL', '').rstrip('/'), 'key': os.getenv(prefix+'_API_KEY', ''), 'model': os.getenv(prefix+'_MODEL', DRAW if role == 'draw' else BRANCHES[role])}

def post(url, key, payload, timeout):
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=timeout) as resp: return json.load(resp)
    except error.HTTPError as exc:
        detail = exc.read(600).decode(errors='replace')
        raise ApiError(f'HTTP {exc.code}: {detail}') from None
    except Exception as exc: raise ApiError(str(exc)) from None

def endpoint(cfg, path):
    if not configured(cfg['base']) or not configured(cfg['key']): raise ApiError('缺少有效的 BASE_URL 或 API_KEY；请修改并保存 .env')
    return cfg['base'] + path

def draw(prompt, mock, timeout, role='draw', raw_path=None):
    cfg = config(role)
    if mock:
        if Image is None: raise ApiError('mock 需要 Pillow: pip install -r requirements.txt')
        image = Image.new('RGB', (512, 512), '#f3e5cb'); pen = ImageDraw.Draw(image)
        pen.rectangle((90, 100, 420, 410), fill='#bd875b'); pen.ellipse((180, 180, 330, 330), fill='#fff6df')
        buf = io.BytesIO(); image.save(buf, 'PNG')
        return buf.getvalue(), {'model': cfg['model'], 'mock': True}
    if cfg['model'].startswith('gemini-') and 'image' in cfg['model']:
        from urllib.parse import urlsplit, urlunsplit
        u = urlsplit(endpoint(cfg, ''))
        base_path = u.path.rstrip('/')
        if base_path.endswith('/v1'):
            base_path = base_path[:-3]
        native_base = urlunsplit((u.scheme, u.netloc, base_path, '', '')).rstrip('/')
        native_url = native_base + '/v1beta/models/' + cfg['model'] + ':generateContent'
        payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                   'generationConfig': {'responseModalities': ['IMAGE']}}
        req = request.Request(native_url, data=json.dumps(payload).encode(),
                              headers={'x-goog-api-key': cfg['key'], 'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=timeout) as resp: out = json.load(resp)
        except error.HTTPError as exc:
            raise ApiError(f'Gemini 生图 HTTP {exc.code}: {exc.read(600).decode(errors="replace")}') from None
        except Exception as exc:
            raise ApiError(f'Gemini 生图请求失败: {exc}') from None
        if raw_path: save_json(raw_path, out)
        parts = [part for candidate in out.get('candidates', [])
                 for part in candidate.get('content', {}).get('parts', [])]
        images = [part.get('inlineData') or part.get('inline_data') for part in parts
                  if part.get('inlineData') or part.get('inline_data')]
        if not images:
            raise ApiError('Gemini 生图接口未返回图片数据')
        try:
            raw = base64.b64decode(images[0]['data'], validate=True)
            image = Image.open(io.BytesIO(raw))
            image.verify()
            image = Image.open(io.BytesIO(raw))
            buf = io.BytesIO()
            image.save(buf, 'PNG')
        except Exception:
            raise ApiError('Gemini 生图返回的数据无法打开') from None
        return buf.getvalue(), {'model': out.get('modelVersion', cfg['model']),
                                 'usage': out.get('usageMetadata'),
                                 'actual_size': [image.width, image.height]}
    if cfg['model'].startswith(('gpt-', 'chat-')) and not cfg['model'].startswith('gpt-image-'):
        tool_model = os.getenv('DRAW_TOOL_MODEL', 'gpt-image-2')
        out = post(endpoint(cfg, '/responses'), cfg['key'], {
            'model': cfg['model'],
            'input': prompt,
            'tools': [{'type': 'image_generation', 'model': tool_model, 'action': 'generate'}],
            'tool_choice': {'type': 'image_generation'},
        }, timeout)
        if raw_path: save_json(raw_path, out)
        calls = [item for item in out.get('output', []) if item.get('type') == 'image_generation_call']
        if not calls or not calls[0].get('result'):
            output_types = [item.get('type', '?') for item in out.get('output', [])]
            raise ApiError('Responses API 未返回图片；该密钥的通道可能不支持 image_generation 工具。'
                           f' 返回状态={out.get("status", "未知")}，输出类型={output_types}')
        try:
            raw = base64.b64decode(calls[0]['result'], validate=True)
        except Exception:
            raise ApiError('Responses API 返回的图片不是有效 Base64') from None
        if Image:
            try: Image.open(io.BytesIO(raw)).verify()
            except Exception: raise ApiError('Responses API 返回的图片无法打开') from None
        return raw, {'model': out.get('model', cfg['model']), 'image_model': tool_model,
                     'usage': out.get('usage'), 'response_id': out.get('id')}
    if not cfg['model'].startswith('gpt-image-'):
        raise ApiError(f'绘图模型 {cfg["model"]} 没有适配的图片生成协议；请使用 gpt-image-* 或 GPT 主模型')
    payload = {'model': cfg['model'], 'prompt': prompt, 'n': 1, 'size': os.getenv('IMAGE_SIZE', '1024x1024')}
    if cfg['model'].startswith('gpt-image-'):
        payload['quality'] = os.getenv('IMAGE_QUALITY', 'high')
    else:
        payload['response_format'] = 'b64_json'
    out = post(endpoint(cfg, '/images/generations'), cfg['key'], payload, timeout)
    if raw_path: save_json(raw_path, out)
    item = (out.get('data') or [None])[0]
    if not item: raise ApiError('绘图接口未返回图片 data')
    if item.get('b64_json'): raw = base64.b64decode(item['b64_json'])
    elif item.get('url'):
        with request.urlopen(item['url'], timeout=timeout) as resp: raw = resp.read()
    else: raise ApiError('绘图响应没有 b64_json 或 url；请按服务商文档调整适配器')
    if Image:
        try: Image.open(io.BytesIO(raw)).verify()
        except Exception: raise ApiError('返回的图片数据无法打开') from None
    return raw, {'model': out.get('model', cfg['model']), 'usage': out.get('usage'), 'created': out.get('created')}

def feedback(role, requirement, checklist, image, mock, timeout, raw_path=None):
    cfg = config(role)
    if mock: return {'checks': [{'id': x['id'], 'status': 'uncertain', 'evidence': 'mock 测试，无真实视觉判断'} for x in checklist], 'priority_fixes': [], 'revised_prompt': requirement}, {'mock': True, 'model': cfg['model']}
    mime = 'image/png' if image[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
    content = [{'type': 'text', 'text': json.dumps({'original_requirement': requirement, 'checklist': checklist}, ensure_ascii=False)}, {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,'+base64.b64encode(image).decode()}}]
    if role == 'gemini':
        from urllib.parse import urlsplit, urlunsplit
        u = urlsplit(cfg['base'])
        base_path = u.path.rstrip('/')
        if base_path.endswith('/v1'):
            base_path = base_path[:-3]
        native_base = urlunsplit((u.scheme, u.netloc, base_path, '', '')).rstrip('/')
        native_url = native_base + '/v1beta/models/' + cfg['model'] + ':generateContent'
        native_payload = {'systemInstruction': {'parts': [{'text': SYSTEM}]}, 'contents': [{'role': 'user', 'parts': [{'text': json.dumps({'original_requirement': requirement, 'checklist': checklist}, ensure_ascii=False)}, {'inline_data': {'mime_type': mime, 'data': base64.b64encode(image).decode()}}]}], 'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'}}
        req = request.Request(native_url, data=json.dumps(native_payload).encode(), headers={'x-goog-api-key': cfg['key'], 'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=timeout) as resp: out = json.load(resp)
        except error.HTTPError as exc:
            raise ApiError(f'Gemini HTTP {exc.code}: {exc.read(600).decode(errors="replace")}') from None
        except Exception as exc:
            raise ApiError(f'Gemini 请求失败: {exc}') from None
        if raw_path: save_json(raw_path.with_suffix('.response.json'), out)
        raw = ''.join(part.get('text', '') for candidate in out.get('candidates', []) for part in candidate.get('content', {}).get('parts', []))
        provider_meta = {'model': out.get('modelVersion', cfg['model']), 'usage': out.get('usageMetadata')}
    else:
        out = post(endpoint(cfg, '/chat/completions'), cfg['key'], {'model': cfg['model'], 'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': content}], 'temperature': 0}, timeout)
        if raw_path: save_json(raw_path.with_suffix('.response.json'), out)
        raw = out['choices'][0]['message']['content']
        provider_meta = {'model': out.get('model', cfg['model']), 'usage': out.get('usage')}
    if isinstance(raw, list): raw = ''.join(x.get('text', '') for x in raw if isinstance(x, dict))
    if raw_path: raw_path.write_text(raw, encoding='utf-8')
    try: parsed = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()))
    except Exception: raise ApiError('反馈不是有效 JSON；原始响应已保存') from None
    ids = {x['id'] for x in checklist}
    checks = parsed.get('checks')
    if not isinstance(checks, list) or {x.get('id') for x in checks} != ids or len(checks) != len(ids): raise ApiError('反馈缺少检查项或 ID 不一致')
    if any(x.get('status') not in ('pass','fail','uncertain') or not isinstance(x.get('evidence'), str) for x in checks): raise ApiError('反馈状态或证据字段无效')
    if not isinstance(parsed.get('revised_prompt'), str) or not parsed['revised_prompt'].strip(): raise ApiError('缺少新提示词')
    return parsed, {**provider_meta, 'raw_response': raw}

def save_json(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def run(requirement, checklist, mock=False, root=Path('runs'), timeout=90, dataset='development', task_id=None, requested_image_size=None, fixed_version=None):
    if not requirement.strip(): raise ValueError('需求不能为空')
    if not checklist: raise ValueError('检查清单不能为空')
    if dataset == 'formal' and (not task_id or not re.fullmatch(r'T\d{2}', task_id) or not fixed_version):
        raise ValueError('正式任务需要 T01–T10 编号和冻结版本')
    task_id = task_id or time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    folder = root/task_id; folder.mkdir(parents=True, exist_ok=False)
    (folder/'original.txt').write_text(requirement, encoding='utf-8'); save_json(folder/'checklist.json', checklist)
    save_json(folder/'initial_request.json', {'model': config('draw')['model'], 'prompt': requirement,
              'requested_size': os.getenv('IMAGE_SIZE', '1024x1024'), 'generation_count': 1})
    if dataset not in ('development', 'formal'):
        raise ValueError('dataset 只能是 development 或 formal')
    manifest = {'task_id': task_id, 'dataset': dataset, 'fixed_version': fixed_version, 'mock': mock, 'started_at': time.time(), 'draw_model': config('draw')['model'], 'branches': {}, 'requested_image_size': requested_image_size or os.getenv('IMAGE_SIZE', '1024x1024'), 'draw_calls': 0, 'attempts': []}
    def recorded_call(kind, branch, model, fn):
        record = {'kind': kind, 'branch': branch, 'model': model, 'started_at': time.time()}
        manifest['attempts'].append(record)
        start = time.monotonic()
        try:
            result = fn()
            record['success'] = True
            return result
        except Exception as exc:
            record['success'] = False
            record['error'] = str(exc)
            raise
        finally:
            record['latency_seconds'] = round(time.monotonic() - start, 2)
            record['finished_at'] = time.time()
            save_json(folder/'manifest.json', manifest)
    try:
        start=time.monotonic(); initial, meta=recorded_call('draw', 'initial', config('draw')['model'], lambda: draw(requirement, mock, timeout, raw_path=folder/'initial_response.json'))
        (folder/'initial.png').write_bytes(initial); manifest['initial']={'metadata': meta, 'latency_seconds': round(time.monotonic()-start,2)}; manifest['actual_image_size']=meta.get('actual_size'); manifest['draw_calls']+=1
    except Exception as exc:
        manifest['initial_error']=str(exc); save_json(folder/'manifest.json',manifest); return folder
    for role in BRANCHES:
        branch_dir=folder/role; branch_dir.mkdir(); rec={'model': config(role)['model']}; manifest['branches'][role]=rec
        save_json(branch_dir/'feedback_request.json', {'model': rec['model'],
                  'original_requirement': requirement, 'checklist': checklist,
                  'system_instruction': SYSTEM, 'image_path': '../initial.png',
                  'image_sha256': hashlib.sha256(initial).hexdigest()})
        start=time.monotonic()
        try:
            for attempt in range(2):
                try:
                    result, meta=recorded_call('feedback', role, config(role)['model'], lambda: feedback(role, requirement, checklist, initial, mock, timeout, raw_path=branch_dir/'raw_response.txt')); break
                except ApiError as exc:
                    if attempt: raise
            rec['feedback_metadata']=meta; rec['feedback_latency_seconds']=round(time.monotonic()-start,2)
            save_json(branch_dir/'feedback.json', result); (branch_dir/'revised_prompt.txt').write_text(result['revised_prompt'], encoding='utf-8')
            save_json(branch_dir/'draw_request.json', {'model': config('draw')['model'],
                      'prompt': result['revised_prompt'], 'requested_size': os.getenv('IMAGE_SIZE', '1024x1024'),
                      'generation_count': 1})
            start=time.monotonic(); image, draw_meta=recorded_call('draw', role, config('draw')['model'], lambda: draw(result['revised_prompt'],mock,timeout,raw_path=branch_dir/'draw_response.json'))
            (branch_dir/'result.png').write_bytes(image); rec['draw_metadata']=draw_meta; rec['draw_latency_seconds']=round(time.monotonic()-start,2); manifest['draw_calls']+=1
        except Exception as exc: rec['error']=str(exc)
        save_json(folder/'manifest.json',manifest)
    manifest['finished_at']=time.time(); save_json(folder/'manifest.json',manifest)
    csv_path=root/f'{dataset}_results.csv'; exists=csv_path.exists()
    with csv_path.open('a',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        if not exists: writer.writerow(['task_id','branch','feedback_model','draw_model','success','error','mock'])
        for role, rec in manifest['branches'].items(): writer.writerow([task_id,role,rec['model'],manifest['draw_model'],(folder/role/'result.png').exists(),rec.get('error',''),mock])
    return folder

def main():
    p=argparse.ArgumentParser(); p.add_argument('--mock',action='store_true'); p.add_argument('--requirement'); p.add_argument('--checklist'); p.add_argument('--check-config',action='store_true'); p.add_argument('--output',default='runs'); args=p.parse_args()
    if args.check_config:
        for role in ('draw',*BRANCHES):
            c=config(role); print(f"{role}: model={c['model']} base_url={'已配置' if configured(c['base']) else '未配置'} key={'已配置' if configured(c['key']) else '未配置'}")
        return
    requirement=args.requirement or input('原始需求: ').strip()
    checklist=json.loads(Path(args.checklist).read_text(encoding='utf-8')) if args.checklist else [{'id':str(i+1),'text':x.strip()} for i,x in enumerate(re.split('[。；;\n]',requirement)) if x.strip()]
    print('检查清单:',json.dumps(checklist,ensure_ascii=False))
    print('计划最多生成 4 张图；真实 API 可能收费。')
    folder=run(requirement,checklist,args.mock,Path(args.output)); print('结果:',folder)
if __name__=='__main__': main()
