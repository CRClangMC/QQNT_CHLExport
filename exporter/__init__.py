from datetime import datetime
import re


def sanitize_filename(filename):
    if filename is None:
        return 'unknown'
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(filename))
    sanitized = sanitized.rstrip(' .')
    return sanitized or 'unknown'


def conversation_filename(filename, with_id=False, identifier=None, nickname=None, remark=None):
    if with_id:
        if nickname and remark and nickname != remark:
            filename = f'{nickname}（{remark}）'
        elif nickname or remark:
            filename = nickname or remark
        if identifier is not None:
            filename = f'{filename or "unknown"}-{identifier}'
    return sanitize_filename(filename)


def format_message_time(timestamp):
    if timestamp is None:
        return "未知时间"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")