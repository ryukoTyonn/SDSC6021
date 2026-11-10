"""Prepare and validate the formal set locally; this module never calls an API."""
import csv
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/maplelee/Desktop/GenAI_十条正式需求与实验交接.docx')
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def source_blocks():
    with ZipFile(SOURCE) as archive:
        body = ET.fromstring(archive.read('word/document.xml')).find('w:body', NS)
    for block in body:
        if block.tag.endswith('}p'):
            yield 'p', ''.join(x.text or '' for x in block.findall('.//w:t', NS))
        elif block.tag.endswith('}tbl'):
            yield 'table', [
                [''.join(x.text or '' for x in cell.findall('.//w:t', NS))
                 for cell in row.findall('w:tc', NS)]
                for row in block.findall('w:tr', NS)
            ]


def extract():
    cases = []
    current = None
    for kind, value in source_blocks():
        if kind == 'p':
            match = re.match(r'^(T\d{2})\s+(.+)$', value)
            if match:
                current = {'task_id': match.group(1), 'split': 'formal',
                           'title': match.group(2), 'original_requirement': None,
                           'checks': [], 'requested_image_size': '1024x1024'}
                cases.append(current)
            elif current and value.startswith('原始需求：'):
                current['original_requirement'] = value[len('原始需求：'):]
        elif current and value and value[0] == ['编号', '固定检查项']:
            current['checks'] = [{'id': row[0], 'text': row[1]} for row in value[1:]]
    return cases


def validate(cases):
    expected = [f'T{i:02d}' for i in range(1, 11)]
    ids = [x.get('task_id') for x in cases]
    assert ids == expected, f'任务编号不连续或重复: {ids}'
    requirements = set()
    for case in cases:
        assert case.get('split') == 'formal'
        requirement = case.get('original_requirement')
        assert isinstance(requirement, str) and requirement.strip()
        assert requirement not in requirements, f'重复需求: {case["task_id"]}'
        requirements.add(requirement)
        checks = case.get('checks')
        assert isinstance(checks, list) and [x.get('id') for x in checks] == [f'C{i}' for i in range(1, 9)], case['task_id']
        texts = [x.get('text') for x in checks]
        assert all(isinstance(x, str) and x.strip() for x in texts)
        assert len(set(texts)) == len(texts), f'重复检查项: {case["task_id"]}'
        assert re.fullmatch(r'\d+x\d+', case['requested_image_size'])
    return True


def main():
    cases = extract()
    validate(cases)
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    snapshot = json.loads((ROOT/'snapshots'/'freeze.json').read_text())
    for case in cases:
        case['fixed_version'] = snapshot['version_id']
    target = {'schema_version': 1, 'source_docx_sha256': source_sha, 'cases': cases}
    (ROOT/'batch_input.json').write_text(json.dumps(target, ensure_ascii=False, indent=2)+'\n')
    rows = []
    for case in cases:
        for image_code in ('A', 'B', 'C', 'D'):
            for check in case['checks']:
                rows.append({'task_id': case['task_id'], 'image_code': image_code,
                             'check_id': check['id'], 'check_text': check['text'],
                             'human_status': '', 'reason': '', 'reviewer': '', 'review_time': ''})
    with (ROOT/'blind_review_template.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    with (ROOT/'human_review_development.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['task_id','check_id','human_status','reason','reviewer','review_time'])
        for task, checks in [('D01', ('C3',)), ('D03', ('C6','C8'))]:
            for check in checks: writer.writerow([task,check,'','','',''])
    budget = {'tasks': 10, 'base_images': 10, 'branch_images': 30,
              'successful_draws_without_control': 40, 'feedback_calls': 30,
              'optional_control_draws': 30, 'successful_draws_with_control': 70,
              'unit_price': None, 'currency': None,
              'note': '单价和失败重试收费规则未核实，金额不估算；实际请求次数可能因失败或重试增加。'}
    (ROOT/'budget_preview.json').write_text(json.dumps(budget, ensure_ascii=False, indent=2)+'\n')
    print(f'validated {len(cases)} cases, 80 checks, {len(rows)} blind-review rows')


if __name__ == '__main__':
    main()
