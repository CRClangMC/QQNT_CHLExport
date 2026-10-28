#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from pathlib import Path

from chat_history_stats import build_report, load_messages


MEMOIR_COUNT = 50
SEPARATOR = '\n' + '=' * 80 + '\n\n'


def main():
    parser = argparse.ArgumentParser(description='汇总目录内所有 QQ JSON 聊天记录')
    parser.add_argument('json_dir', type=Path, help='包含聊天记录 JSON 的目录')
    args = parser.parse_args()

    json_dir = args.json_dir.expanduser().resolve()
    if not json_dir.is_dir():
        parser.error(f'目录不存在：{json_dir}')

    json_paths = sorted(json_dir.glob('*.json'), key=lambda path: path.name.casefold())
    if not json_paths:
        parser.error(f'目录内没有 JSON 文件：{json_dir}')

    reports = []
    failures = []
    for index, json_path in enumerate(json_paths, 1):
        print(f'[{index}/{len(json_paths)}] 正在统计：{json_path.name}')
        try:
            messages = load_messages(json_path)
            reports.append(build_report(messages, json_path.stem, memoir_count=MEMOIR_COUNT))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            failures.append(f'{json_path.name}：{error}')
            print(f'  跳过：{error}')

    if not reports:
        parser.error('没有可成功统计的 JSON 文件')

    header = [
        'QQ时光统计局：全部聊天记录汇总',
        f'生成时间：{datetime.now():%Y年%m月%d日%H时%M分%S秒}',
        f'成功统计：{len(reports)} 个文件；跳过：{len(failures)} 个文件。',
    ]
    if failures:
        header.extend(['', '【跳过的文件】', *failures])

    output_path = json_dir / 'QQ时光统计局_全部统计.txt'
    output = '\n'.join(header) + SEPARATOR + SEPARATOR.join(reports)
    output_path.write_text(output, encoding='utf-8-sig')
    print(f'\n汇总完成：{output_path}')


if __name__ == '__main__':
    main()