"""Formal runner. Requires an explicit --start-paid flag; preview is local only."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app import BRANCHES, SYSTEM, config, run
from prepare import ROOT, validate


def load_frozen():
    batch = json.loads((ROOT/'batch_input.json').read_text())
    freeze = json.loads((ROOT/'snapshots'/'freeze.json').read_text())
    validate(batch['cases'])
    assert all(x['fixed_version'] == freeze['version_id'] for x in batch['cases'])
    assert SYSTEM == freeze['evaluation_instruction'], '评价提示词与冻结版不一致'
    assert {role: config(role)['model'] for role in ('draw', *BRANCHES)} == freeze['model_ids'], '模型 ID 与冻结版不一致'
    cfg = freeze['configuration_without_keys']
    for role in ('draw', *BRANCHES):
        assert config(role)['base'] == cfg[role+'_base_url'], f'{role} 地址与冻结版不一致'
    import os
    assert os.getenv('IMAGE_SIZE', '1024x1024') == cfg['requested_image_size']
    assert os.getenv('IMAGE_QUALITY', 'high') == cfg['image_quality']
    assert all(config(role)['key'] for role in ('draw', *BRANCHES)), '有密钥未配置'
    return batch, freeze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-paid', action='store_true', help='明确启动付费正式批量实验')
    args = parser.parse_args()
    batch, freeze = load_frozen()
    if not args.start_paid:
        print(f"预检通过：{len(batch['cases'])} 条，计划 40 次成功绘图、30 次反馈；版本 {freeze['version_id']}。未调用 API。")
        return
    data_root = ROOT/'data'
    data_root.mkdir(exist_ok=True)
    for case in batch['cases']:
        task_id = case['task_id']
        target = data_root/task_id
        if target.exists():
            raise RuntimeError(f'{task_id} 已存在，停止以避免覆盖；先人工处理原始记录')
        folder = run(case['original_requirement'], case['checks'], False, data_root,
                     freeze['configuration_without_keys']['default_timeout_seconds'],
                     dataset='formal', task_id=task_id,
                     requested_image_size=case['requested_image_size'],
                     fixed_version=case['fixed_version'])
        print(f'{task_id}: {folder}')


if __name__ == '__main__':
    main()
