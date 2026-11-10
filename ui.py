import json
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"
from pathlib import Path
import gradio as gr
from app import BRANCHES, config, configured, run

def execute(req, checklist_text, mock):
    try:
        checklist=json.loads(checklist_text)
        if not isinstance(checklist,list) or any('id' not in x or 'text' not in x for x in checklist): raise ValueError('检查清单需为含 id 和 text 的 JSON 数组')
        folder=run(req,checklist,mock)
        manifest=json.loads((folder/'manifest.json').read_text())
        images=[str(folder/'initial.png') if (folder/'initial.png').exists() else None]
        feedback=[]
        for role in BRANCHES:
            p=folder/role/'feedback.json'; feedback.append(p.read_text() if p.exists() else manifest.get('branches',{}).get(role,{}).get('error',''))
            images.append(str(folder/role/'result.png') if (folder/role/'result.png').exists() else None)
        return str(folder),json.dumps(manifest,ensure_ascii=False,indent=2),*images,*feedback,str(folder/'manifest.json')
    except Exception as exc: raise gr.Error(str(exc))

with gr.Blocks(title='多模型图像反馈实验') as demo:
    gr.Markdown('# 多模型图像反馈实验\n每次运行最多生成 4 张图；真实接口可能收费。请只点击一次并等待完成。')
    req=gr.Textbox(label='原始需求',lines=4)
    checklist=gr.Code(label='可编辑检查清单 JSON',language='json',value='[{"id":"1","text":"检查主体是否符合要求"}]')
    mock=gr.Checkbox(label='mock 模式（不调用 API）',value=True)
    gr.Textbox(label='配置状态',value='；'.join(f"{r}: {config(r)['model']}，地址{'已配置' if configured(config(r)['base']) else '未配置'}，密钥{'已配置' if configured(config(r)['key']) else '未配置'}" for r in ('draw',*BRANCHES)),interactive=False)
    button=gr.Button('开始运行（计划最多 4 张）')
    folder=gr.Textbox(label='保存目录'); manifest=gr.Code(label='运行记录',language='json')
    images=[gr.Image(label=x) for x in ('初始图','GPT 新图','Gemini 新图','DeepSeek 新图')]
    feedback=[gr.Textbox(label=x,lines=8) for x in ('GPT 反馈','Gemini 反馈','DeepSeek 反馈')]
    download=gr.File(label='下载本次 manifest')
    button.click(execute,[req,checklist,mock],[folder,manifest,*images,*feedback,download],concurrency_limit=1)
if __name__=='__main__': demo.launch()
