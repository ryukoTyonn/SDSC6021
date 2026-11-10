"""盲评结果汇总：把 ratings.csv 变成可以写进报告的数字。

只在人工评分**做完之后**运行。它做三件事：
  1. 用 private/blind_mapping.json 把匿名码还原成来源（initial / gpt / gemini / deepseek）；
  2. 算每个来源的通过率、相对初图的提升、以及每条检查项的改善情况；
  3. 若有两名评分员，算一致性（Cohen's kappa）。

用法：
    python analyze_blind.py
    python analyze_blind.py --out "D:\\...\\output"

输出：
    output/盲评结果汇总.md
    output/blind_summary_by_source.csv
    output/blind_summary_by_task.csv
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_FORMAL = Path(__file__).resolve().parent.parent / "formal"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "reports"
ORDER = ["initial", "gpt", "gemini", "deepseek"]
LABEL = {"initial": "初图", "gpt": "GPT", "gemini": "Gemini", "deepseek": "DeepSeek"}


def rate(counter):
    """pass / (pass + fail)，uncertain 单独报，不计入分母。"""
    p, f = counter.get("pass", 0), counter.get("fail", 0)
    base = p + f
    return (p / base if base else None), base


def fmt(x, digits=1):
    return "—" if x is None else f"{x*100:.{digits}f}%"


def load_rows(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def item_map(rows, has_img):
    """(task, code, check) -> status，只保留有效状态与有图的条目。"""
    return {(r["task_id"], r["image_code"], r["check_id"]): r["human_status"]
            for r in rows
            if r["human_status"] in ("pass", "fail", "uncertain")
            and (r["task_id"], r["image_code"]) in has_img}


def cohen_kappa(a_map, b_map):
    keys = set(a_map) & set(b_map)
    if not keys:
        return None
    n = len(keys)
    po = sum(1 for k in keys if a_map[k] == b_map[k]) / n
    ca, cb = Counter(a_map[k] for k in keys), Counter(b_map[k] for k in keys)
    pe = sum((ca[s] / n) * (cb[s] / n) for s in set(ca) | set(cb))
    k = (po - pe) / (1 - pe) if pe != 1 else 0.0
    return n, po, k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal", default=str(DEFAULT_FORMAL))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--csv", default=None, help="主评分表，默认 formal/blind_review/ratings.csv")
    ap.add_argument("--extra-csv", nargs="*", default=[],
                    help="其他评分员的评分表，用于算一致性")
    args = ap.parse_args()

    formal = Path(args.formal)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    primary_path = Path(args.csv) if args.csv else formal / "blind_review" / "ratings.csv"
    ratings = load_rows(primary_path)
    mapping = json.loads((formal / "private" / "blind_mapping.json").read_text(encoding="utf-8"))
    batch = json.loads((formal / "batch_input.json").read_text(encoding="utf-8"))
    titles = {c["task_id"]: c.get("title", "") for c in batch["cases"]}
    src_of = {(m["task_id"], m["image_code"]): m["source"] for m in mapping}

    # 只统计真有图片的行
    has_img = {(m["task_id"], m["image_code"]) for m in mapping}
    used = [r for r in ratings
            if r["human_status"] in ("pass", "fail", "uncertain")
            and (r["task_id"], r["image_code"]) in has_img]
    skipped = [r for r in ratings
               if r["human_status"] in ("pass", "fail", "uncertain")
               and (r["task_id"], r["image_code"]) not in has_img]

    if not used:
        raise SystemExit("ratings.csv 里还没有任何评分（human_status 全为空），先按 05 号文档打分。")

    reviewers = Counter(r["reviewer"] for r in used if r["reviewer"])
    total_rows = sum(1 for r in ratings if (r["task_id"], r["image_code"]) in has_img)

    # ---- 按来源 ----
    by_src = defaultdict(Counter)
    for r in used:
        by_src[src_of[(r["task_id"], r["image_code"])]][r["human_status"]] += 1
    src_rows = []
    init_rate, _ = rate(by_src["initial"])
    for s in ORDER:
        c = by_src[s]
        p, base = rate(c)
        delta = None if (p is None or init_rate is None) else p - init_rate
        src_rows.append({
            "source": s, "label": LABEL[s],
            "pass": c.get("pass", 0), "fail": c.get("fail", 0),
            "uncertain": c.get("uncertain", 0), "scored": base,
            "pass_rate": p, "delta_vs_initial": delta,
        })

    # ---- 按任务 × 来源 ----
    by_task = defaultdict(lambda: defaultdict(Counter))
    for r in used:
        by_task[r["task_id"]][src_of[(r["task_id"], r["image_code"])]][r["human_status"]] += 1

    # ---- 按检查项（初图 vs 三个分支合计）----
    by_check = defaultdict(lambda: defaultdict(Counter))
    for r in used:
        s = src_of[(r["task_id"], r["image_code"])]
        key = (r["task_id"], r["check_id"], r["check_text"])
        by_check[key]["initial" if s == "initial" else "branches"][r["human_status"]] += 1

    improved, regressed = [], []
    for (t, cid, text), d in sorted(by_check.items()):
        pi, bi = rate(d["initial"])
        pb, bb = rate(d["branches"])
        if pi is None or pb is None:
            continue
        if pb - pi >= 0.4:
            improved.append((t, cid, text, pi, pb))
        elif pb - pi <= -0.4:
            regressed.append((t, cid, text, pi, pb))

    # ---- 评分员一致性 ----
    base_map = item_map(ratings, has_img)
    kappa_txt = "只有一份评分表，无法计算一致性。要算 kappa，让第二名评分员用 `--csv ratings_r2.csv` 另存一份再传入 `--extra-csv`。"
    if args.extra_csv:
        parts = []
        for p in args.extra_csv:
            res = cohen_kappa(base_map, item_map(load_rows(p), has_img))
            if res is None:
                parts.append(f"`{Path(p).name}` 与主表没有重叠的已评条目，跳过。")
                continue
            n, po, k = res
            parts.append(
                f"`{Path(p).name}` 与主表重叠 {n} 项，一致率 {po*100:.1f}%，"
                f"Cohen's kappa = {k:.3f}（{'可接受' if k >= 0.6 else '偏低，需先校准标准再全量打分'}）。")
        kappa_txt = "\n".join("- " + x for x in parts)

    # ---- 写 CSV ----
    with (out / "blind_summary_by_source.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(src_rows[0]))
        w.writeheader()
        w.writerows(src_rows)

    with (out / "blind_summary_by_task.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "title", "initial", "gpt", "gemini", "deepseek"])
        for t in sorted(by_task):
            row = [t, titles.get(t, "")]
            for s in ORDER:
                p, _ = rate(by_task[t][s])
                row.append("" if p is None else f"{p*100:.1f}")
            w.writerow(row)

    # ---- 写 Markdown ----
    L = []
    L.append("# 人工盲评结果汇总")
    L.append("")
    L.append(f"数据来源：`formal/blind_review/ratings.csv`；"
             f"已评 {len(used)} / {total_rows} 条有效记录"
             f"（{len(skipped)} 条填在无图行上，已剔除）。")
    L.append(f"评分员：{'、'.join(reviewers) if reviewers else '未填写'}。")
    L.append("")
    L.append("口径：通过率 = pass / (pass + fail)，`uncertain` 不计入分母、单独列出；"
             "提升 = 该来源通过率 − 初图通过率。")
    L.append("")
    L.append("## 一、各来源总体表现")
    L.append("")
    L.append("| 来源 | 通过 | 不通过 | 看不清 | 有效项 | 通过率 | 相对初图 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in src_rows:
        d = "—" if r["delta_vs_initial"] is None else f"{r['delta_vs_initial']*100:+.1f} pp"
        L.append(f"| {r['label']} | {r['pass']} | {r['fail']} | {r['uncertain']} | "
                 f"{r['scored']} | {fmt(r['pass_rate'])} | {d} |")
    L.append("")
    L.append("## 二、逐任务通过率（%）")
    L.append("")
    L.append("| 任务 | 标题 | 初图 | GPT | Gemini | DeepSeek |")
    L.append("|---|---|---|---|---|---|")
    for t in sorted(by_task):
        cells = []
        for s in ORDER:
            p, _ = rate(by_task[t][s])
            cells.append("—" if p is None else f"{p*100:.1f}")
        L.append(f"| {t} | {titles.get(t,'')} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("## 三、变化最明显的检查项")
    L.append("")
    if improved:
        L.append("**明显变好（+40pp 以上）**")
        L.append("")
        for t, cid, text, pi, pb in improved:
            L.append(f"- {t} {cid} {text}：{pi*100:.0f}% → {pb*100:.0f}%")
        L.append("")
    if regressed:
        L.append("**明显变差（−40pp 以上）**")
        L.append("")
        for t, cid, text, pi, pb in regressed:
            L.append(f"- {t} {cid} {text}：{pi*100:.0f}% → {pb*100:.0f}%")
        L.append("")
    if not improved and not regressed:
        L.append("没有出现 ±40pp 以上的单项变化，改善更可能是分散的、非单点突破。")
        L.append("")
    L.append("## 四、评分员一致性")
    L.append("")
    L.append(kappa_txt)
    L.append("")
    L.append("## 五、写报告时的注意事项")
    L.append("")
    L.append("1. 这是**单轮**实验的结果，不能声称“多轮迭代有效”。")
    L.append("2. 没有随机对照组，`initial → 分支` 的差异里仍混有绘图随机性；"
             "措辞用“观察到提升”，不要写“证明提升”。")
    L.append("3. 三个分支用的是同一个绘图模型、同一份清单，差别只来自反馈模型，"
             "这是可以下的因果结论。")
    L.append(f"4. 缺失分支（无图）共 {len(skipped)} 条，报告里要说明剔除方式，不要补 0。")

    (out / "盲评结果汇总.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:40]))
    print(f"\n已写出：{out/'盲评结果汇总.md'}")
    print(f"        {out/'blind_summary_by_source.csv'}")
    print(f"        {out/'blind_summary_by_task.csv'}")


if __name__ == "__main__":
    main()
