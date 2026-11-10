"""环境自检：确认当前解释器能跑通 genai_feedback 的 CLI 与 UI。

用法（在 PyCharm 里右键 Run，或在项目根目录执行）：
    python tools/check_env.py

只做只读检查，不调用任何付费 API，不写入项目目录。
退出码 0 = 全部通过。
"""
import importlib
import json
import os
import socket
import sys
import time
from pathlib import Path

PROJECT = Path(os.environ.get("GENAI_FEEDBACK_DIR", Path(__file__).resolve().parent.parent))

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail))
    except Exception as exc:  # noqa: BLE001
        results.append((False, name, f"{type(exc).__name__}: {exc}"))


def c_python():
    v = sys.version_info
    assert v >= (3, 9), f"需要 Python>=3.9，当前 {v.major}.{v.minor}"
    return f"{v.major}.{v.minor}.{v.micro}"


def c_imports():
    mods = ["PIL", "dotenv", "gradio", "gradio_client", "huggingface_hub"]
    out = []
    for m in mods:
        mod = importlib.import_module(m)
        out.append(f"{m}={getattr(mod, '__version__', '?')}")
    return ", ".join(out)


def c_starlette_compat():
    """gradio 4.x 会在 starlette>=1.0 上崩，这里确认版本组合是对的。"""
    import gradio
    import starlette

    g = gradio.__version__
    s = starlette.__version__
    major_s = int(s.split(".")[0])
    major_g = int(g.split(".")[0])
    assert not (major_g < 6 and major_s >= 1), (
        f"gradio {g} 与 starlette {s} 不兼容：会抛 "
        "TypeError: unhashable type: 'dict'，请升级 gradio 到 6.x"
    )
    return f"gradio {g} + starlette {s} 组合正常"


def c_project_files():
    need = [
        "app.py",
        "ui.py",
        "requirements.txt",
        ".env",
        "formal/batch_input.json",
        "formal/snapshots/freeze.json",
    ]
    missing = [f for f in need if not (PROJECT / f).exists()]
    assert not missing, f"缺少文件: {missing}"
    return f"{len(need)} 个关键文件齐全"


def c_app_import():
    sys.path.insert(0, str(PROJECT))
    os.chdir(PROJECT)  # app.py 用 load_dotenv() 读当前目录的 .env
    import app

    roles = {r: app.config(r) for r in ("draw", *app.BRANCHES)}
    lines = []
    for r, cfg in roles.items():
        ok_base = app.configured(cfg["base"])
        ok_key = app.configured(cfg["key"])
        assert ok_base and ok_key, f"{r} 的 BASE_URL/API_KEY 未配置"
        lines.append(f"{r}={cfg['model']}")
    return " / ".join(lines)


def c_mock_pipeline():
    """跑一次 mock 全流程到临时目录，验证编排逻辑（不花钱）。"""
    import tempfile

    import app

    req = "木质桌面上恰好两个红苹果，位于蓝色杯子左边。"
    checklist = [
        {"id": "C1", "text": "木质桌面"},
        {"id": "C2", "text": "恰好两个红苹果"},
        {"id": "C3", "text": "苹果在蓝色杯子左边"},
    ]
    with tempfile.TemporaryDirectory() as td:
        folder = app.run(req, checklist, mock=True, root=Path(td))
        made = {
            "initial.png": (folder / "initial.png").exists(),
            "manifest.json": (folder / "manifest.json").exists(),
        }
        for role in app.BRANCHES:
            made[f"{role}/result.png"] = (folder / role / "result.png").exists()
            made[f"{role}/feedback.json"] = (folder / role / "feedback.json").exists()
        missing = [k for k, v in made.items() if not v]
        assert not missing, f"mock 流程缺产物: {missing}"
        return f"mock 全流程 OK（{len(made)} 个产物）"


def c_ui_build():
    """构建 Gradio 界面并起一次服务、探活后立即关闭。"""
    sys.path.insert(0, str(PROJECT))
    os.chdir(PROJECT)
    import urllib.request

    import ui

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ui.demo.launch(
        server_port=port,
        server_name="127.0.0.1",
        prevent_thread_lock=True,
        quiet=True,
        inbrowser=False,
    )
    time.sleep(1.0)
    code = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).status
    assert code == 200, f"HTTP {code}"
    return f"UI 可访问（127.0.0.1:{port} → 200）"


def c_formal_preflight():
    """正式实验包的冻结校验，不调用 API。"""
    sys.path.insert(0, str(PROJECT))
    os.chdir(PROJECT)
    sys.path.insert(0, str(PROJECT / "formal"))
    import run_formal

    batch, freeze = run_formal.load_frozen()
    return f"{len(batch['cases'])} 条正式任务，版本 {freeze['version_id']}"


checks = [
    ("Python 版本", c_python),
    ("依赖导入", c_imports),
    ("gradio/starlette 组合", c_starlette_compat),
    ("项目关键文件", c_project_files),
    ("app.py 配置读取", c_app_import),
    ("mock 全流程", c_mock_pipeline),
    ("Gradio UI 启动", c_ui_build),
    ("正式实验预检", c_formal_preflight),
]

for name, fn in checks:
    check(name, fn)

print("=" * 72)
print(f"环境自检  |  {PROJECT}")
print("=" * 72)
failed = 0
for ok, name, detail in results:
    flag = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"[{flag}] {name:<20} {detail}")
print("-" * 72)
print(f"结果：{len(results) - failed}/{len(results)} 通过")
sys.exit(0 if failed == 0 else 1)
