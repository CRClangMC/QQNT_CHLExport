import re

def sanitize_filename(filename):
    illegal_chars = r'[<>:"/\\|?*]'
    if filename is None:
        return 'unknown'
    if isinstance(filename, int):
        filename = str(filename)
    return re.sub(illegal_chars, '_', str(filename))