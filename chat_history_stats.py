#!/usr/bin/env python3
import argparse
import calendar
import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path


TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def parse_time(value):
    return datetime.strptime(value, TIME_FORMAT)


def format_time(value):
    return value.strftime('%Y年%m月%d日%H时%M分%S秒')


def add_years(value, years):
    year = value.year + years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)


def add_months(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def format_span(start, end):
    if end < start:
        start, end = end, start

    years = end.year - start.year
    cursor = add_years(start, years)
    if cursor > end:
        years -= 1
        cursor = add_years(start, years)

    months = (end.year - cursor.year) * 12 + end.month - cursor.month
    month_cursor = add_months(cursor, months)
    if month_cursor > end:
        months -= 1
        month_cursor = add_months(cursor, months)

    remainder = end - month_cursor
    hours, seconds = divmod(remainder.seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{years}年{months}月{remainder.days}日{hours}时{minutes}分{seconds}秒'


def is_quoted(label):
    return label.startswith('[被引用的消息]')


def display_content(message):
    parts = []
    for item in message.get('contents') or []:
        if not isinstance(item, list) or len(item) < 2:
            continue
        label, value = str(item[0]), item[1]
        if is_quoted(label) or label in ('[图片]', '[语音]', '[视频]'):
            continue
        text = '' if value is None else str(value).strip().replace('\r', ' ').replace('\n', ' / ')
        if text:
            parts.append(text if label == '[文本]' else f'{label}{text}')
    return '；'.join(parts)


def weighted_time_sample(candidates, count):
    if len(candidates) <= count:
        return candidates[:]
    if count == 1:
        return [random.choice(candidates)]

    selected = [candidates[0], candidates[-1]]
    remaining = candidates[1:-1]
    start = candidates[0]['_time']
    total_seconds = max((candidates[-1]['_time'] - start).total_seconds(), 1)
    spacing = max(total_seconds / (count - 1), 1)
    for index in range(1, count - 1):
        target_seconds = total_seconds * index / (count - 1)
        weights = []
        for message in remaining:
            message_seconds = (message['_time'] - start).total_seconds()
            distance = abs(message_seconds - target_seconds)
            weights.append(1 / (1 + distance / spacing) ** 2)
        chosen = random.choices(remaining, weights=weights, k=1)[0]
        selected.append(chosen)
        remaining.remove(chosen)

    return selected


def sample_lines(messages, counterpart, count, cover_time_span=False):
    candidates = [message for message in messages if message['direction'] in ('收', '发') and display_content(message)]
    sample_count = min(count, len(candidates))
    if cover_time_span:
        selected = weighted_time_sample(candidates, sample_count)
    else:
        selected = random.sample(candidates, sample_count)
    selected.sort(key=lambda message: message['_time'])
    lines = []
    for message in selected:
        sender = counterpart if message['direction'] == '收' else '我'
        lines.append(f"{message['time']} [{sender}] {display_content(message)}")
    return lines


def build_report(messages, counterpart, memoir_count=200):
    messages.sort(key=lambda message: message['_time'])
    bilateral = [message for message in messages if message['direction'] in ('收', '发')]
    if not bilateral:
        raise ValueError('JSON 中没有 direction 为“收”或“发”的消息')

    received = sum(message['direction'] == '收' for message in bilateral)
    sent = sum(message['direction'] == '发' for message in bilateral)
    quoted = Counter()
    media = Counter()
    voice = Counter()
    for message in bilateral:
        direction = message['direction']
        for item in message.get('contents') or []:
            if not isinstance(item, list) or not item:
                continue
            label = str(item[0])
            if is_quoted(label):
                quoted[direction] += 1
            elif label in ('[图片]', '[表情]'):
                media[direction] += 1
            elif label == '[语音]':
                voice[direction] += 1

    longest_start = bilateral[0]['_time']
    longest_end = bilateral[0]['_time']
    for previous, current in zip(bilateral, bilateral[1:]):
        if current['_time'] - previous['_time'] > longest_end - longest_start:
            longest_start, longest_end = previous['_time'], current['_time']

    daily = Counter(message['_time'].date() for message in bilateral)
    busiest_day = min((day for day, count in daily.items() if count == max(daily.values())))
    busiest_messages = [message for message in bilateral if message['_time'].date() == busiest_day]
    busiest_received = sum(message['direction'] == '收' for message in busiest_messages)
    busiest_sent = sum(message['direction'] == '发' for message in busiest_messages)

    first_time = bilateral[0]['_time']
    last_time = bilateral[-1]['_time']
    now = datetime.now()
    lines = [
        f'QQ时光统计局：截至{format_time(last_time)}为止，你和{counterpart}共有{len(bilateral)}条消息。',
        '',
        '【收发统计】',
        f'{counterpart}发{received}条，我发{sent}条。',
        f'被引用消息：{counterpart}发出的消息中有{quoted["收"]}条，我发出的消息中有{quoted["发"]}条，总计{quoted["收"] + quoted["发"]}条。',
        f'图片/表情包：{counterpart}发{media["收"]}张，我发{media["发"]}张，总计{media["收"] + media["发"]}张。',
        f'语音：{counterpart}发{voice["收"]}条，我发{voice["发"]}条，总计{voice["收"] + voice["发"]}条。',
        '',
        '【时间统计】',
        f'最长未聊天时间跨度：{format_span(longest_start, longest_end)}（{format_time(longest_start)} 至 {format_time(longest_end)}）',
        f'最早消息记录：{format_time(first_time)}，距今{format_span(first_time, now)}。',
        '',
        '【最多聊天日】',
        f'{busiest_day:%Y年%m月%d日}，共{len(busiest_messages)}条：{counterpart}发{busiest_received}条，我发{busiest_sent}条。',
        '随机抽取当天10条消息（按时间排序）：',
        *sample_lines(busiest_messages, counterpart, 10),
        '',
        '【时光回忆录】',
        f'按时间跨度加权随机抽取{memoir_count}条非图片、非语音、非视频消息（按时间排序）：',
        *sample_lines(bilateral, counterpart, memoir_count, cover_time_span=True),
    ]
    return '\n'.join(lines) + '\n'


def load_messages(json_path):
    with json_path.open('r', encoding='utf-8-sig') as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError('JSON 顶层必须是消息数组')

    messages = []
    for index, message in enumerate(data, 1):
        if not isinstance(message, dict) or not message.get('time'):
            continue
        try:
            message['_time'] = parse_time(message['time'])
        except (TypeError, ValueError) as error:
            raise ValueError(f'第 {index} 条消息时间格式无效：{error}') from error
        messages.append(message)
    return messages


def main():
    parser = argparse.ArgumentParser(description='统计 QQ JSON 聊天记录')
    parser.add_argument('json_path', type=Path, help='聊天记录 JSON 文件路径')
    parser.add_argument('-name', help='对方备注名，默认使用 JSON 文件名')
    args = parser.parse_args()

    json_path = args.json_path.expanduser().resolve()
    counterpart = args.name or json_path.stem
    try:
        messages = load_messages(json_path)
        report = build_report(messages, counterpart)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))

    output_path = json_path.with_name(f'{json_path.stem}_时光统计.txt')
    output_path.write_text(report, encoding='utf-8-sig')
    print(report)
    print(f'统计结果已保存到：{output_path}')


if __name__ == '__main__':
    main()