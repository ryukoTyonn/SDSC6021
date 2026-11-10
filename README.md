# 多模型图像反馈实验

在 Mac 的 VS Code 终端运行。需要 Python 3.9+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

把 `.env` 中的地址、模型 ID 和密钥改成服务商文档给出的真实值。密钥只保存在本机。模型名是用户给出的配置，尚未验证服务商实际支持。

```bash
python app.py --mock --requirement '画一家咖啡店，桌上有两个蓝色杯子。'
python ui.py
```

UI 默认 mock；取消勾选才会调用真实 API。命令行真实运行前，在终端执行 `set -a; source .env; set +a`，然后 `python app.py --check-config`，再运行 `python app.py --requirement '...'`。UI 也需先加载 `.env`，或在代码启动时由 python-dotenv 读取。一次任务最多四次成功绘图，失败请求可能仍收费。实际费用与失败计费以服务商账单为准。

结果保存在 `runs/<task_id>/`：原始需求、检查清单、初图、各分支反馈与新图、manifest；开发调试汇总在 `runs/development_results.csv`；正式实验需要显式使用 `run(..., dataset="formal")`，写入 `runs/formal_results.csv`。mock 图仅用于检查流程，不能作为实验结果。

目前适配器按 OpenAI 风格 `/chat/completions` 多模态输入和 `/images/generations` 图像输出编写。若服务商格式不同，需要按文档修改 `app.py` 的 `feedback()` 与 `draw()`。图片输入被拒绝时，该分支记录错误并继续其他分支。HTTP 错误通常表示地址、模型 ID、权限或余额不匹配；图片数据错误表示绘图响应格式需调整。真实连接是否成功，需要用服务商文档和密钥运行后确认。

Gemini 分支使用原生 `v1beta/models/{model}:generateContent`，发送 PNG/JPEG 图片字节。`GEMINI_BASE_URL` 可写中转站根地址或以 `/v1` 结尾的地址。绘图分支使用 `POST /images/generations`；你提供的 dm-fox 示例对应 `DRAW_BASE_URL=https://dm-fox.rjj.cc/codex/v1`，但只有该平台发放的 Key 才应填入对应 `DRAW_API_KEY`。`gpt-image-*` 默认传 `quality=high`，可通过 `IMAGE_QUALITY` 修改。

## 绘图通道说明

`DRAW_MODEL=gpt-image-*` 时程序调用 `POST /images/generations`；`DRAW_MODEL=gpt-6.1-sol` 等 GPT 主模型时调用 `POST /responses`，并要求该通道支持 `image_generation` 工具。`DRAW_TOOL_MODEL` 指定工具实际使用的图片模型，默认 `gpt-image-2`。主模型本身不会直接输出图片。

同一中转站可能把不同 API Key 绑定到不同通道。已验证当前 `code1.newcli.com` 的 codex 通道拒绝 `/images/generations`；其 `/responses` 虽返回成功，却没有 `image_generation_call`。要完成真实生图，需在 `DRAW_API_KEY` 中使用明确支持图片接口或生图工具的密钥，并按该通道文档设置 `DRAW_BASE_URL` 和 `DRAW_MODEL`。程序会在没有图片结果时报明确错误，不把文本响应当图片。

Gemini 图片模型（例如 `gemini-3.1-flash-image`）也可作为绘图模型：将 `DRAW_BASE_URL` 设为 Gemini 中转站地址、`DRAW_API_KEY` 设为该站可用的 Gemini 密钥、`DRAW_MODEL` 设为图片模型 ID。程序会调用原生 `generateContent` 并保存返回的 PNG。当前账号若返回“额度上限”，需要平台恢复额度或更换有额度的密钥，程序无法绕过。

Gemini 绘图接口可能忽略 `IMAGE_SIZE`；运行记录同时保存请求尺寸与实际返回尺寸，以实际尺寸为实验依据。
