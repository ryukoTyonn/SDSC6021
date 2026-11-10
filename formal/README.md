# 正式实验准备包

本目录仅准备 T01–T10。当前 `data/` 不含运行结果，`formal_results.csv` 尚未创建。开发集的 D01–D03 仍在项目 `runs/` 下，其汇总为 `runs/development_results.csv`。

`batch_input.json` 保存逐字提取的原始需求与 C1–C8 检查项；`prepare.py` 从桌面交接 DOCX 重建并校验编号、重复任务、重复需求及检查项。`snapshots/freeze.json` 记录模型 ID、统一评价指令、清单规则和无密钥配置。`snapshots/genai_feedback_preformal_20261108.zip` 是准备前代码归档。`human_review_development.csv` 保留 D01 C3 与 D03 C6/C8 的人工复核空栏。

`blind_review_template.csv` 为 10 条任务 × 4 张图 × 8 项，共 320 行。正式图像生成后应随机分配匿名码，另行保存 `image_code → branch` 映射；评分员只看匿名图，填写 `human_status`、`reason`、`reviewer` 和 `review_time`。任务级汇总表在人工盲评后生成，不以模型反馈作为人工真值。

预算：10 条任务计划 40 次成功绘图、30 次反馈；若增加同预算随机对照，计划最多 70 次成功绘图。平台单价和失败重试收费规则未核实，故不计算金额。正式运行上限应另外核对实际平台余额和费用。

本地预检命令：

```bash
.venv/bin/python formal/run_formal.py
```

此命令仅校验冻结配置和批量输入，不调用 API。用户明确启动正式实验后，才使用 `--start-paid`。正式执行目录为 `formal/data/T01` 至 `formal/data/T10`，结果文件为 `formal/data/formal_results.csv`。已有编号目录会拒绝覆盖。正式运行中不得更改清单、评价指令和模型配置。
