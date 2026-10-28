from ast import literal_eval
from functools import lru_cache
from pathlib import Path
import re
import shutil
from lxml import etree as lxml_etree

from humanize import naturalsize
from unicodedata import category

from emojis import emojis

pic_path = ""
pic_source_path = ""
voice_path = ""
voice_source_paths = ()

__all__ = [
    "BaseText",
    "BaseImage",
    "BaseFile",
    "BaseVoice",
    "BaseVideo",
    "BaseEmoji",
    "BaseNotice",
    "BaseRedPacket",
    "BaseApplication",
    "BaseCall",
    "BaseFeed",
]


def readable_file_size(file_size):
    """
    Returns a human-readable file size.
    """
    return naturalsize(file_size, binary=True, format="%.2f") if file_size else None


class BaseText:
    def __init__(self, element):
        self.text = element.text

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseImage:
    def __init__(self, element):
        self.text = element.imageText
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)
        self.file_path = element.imageFilePath
        self.file_url = element.imageUrlOrigin

        md5_candidates = self._get_md5_candidates(element)
        self.cache_path = self._get_cache_path(
            element.original,
            tuple(md5_candidates),
            Path(pic_source_path) if pic_source_path else Path(pic_path),
            Path(pic_path),
        )

        self.content = self._get_content()

    @staticmethod
    @lru_cache(maxsize=4096)
    def _get_cache_path(original, md5_candidates, source_path, output_path):
        for md5_value in md5_candidates:
            cached_file = BaseImage._find_modern_cache_file(source_path, md5_value)
            if cached_file:
                output_path.mkdir(parents=True, exist_ok=True)
                destination = output_path / f"{md5_value}{cached_file.suffix.lower()}"
                if not destination.exists() or destination.stat().st_size != cached_file.stat().st_size:
                    shutil.copy2(cached_file, destination)
                return destination

        if not md5_candidates:
            return None

        def crc64(raw_str):
            _crc64_table = [0] * 256
            for i in range(256):
                bf = i
                for _ in range(8):
                    bf = bf >> 1 ^ -7661587058870466123 if bf & 1 else bf >> 1
                _crc64_table[i] = bf
            value = -1
            for char in raw_str:
                value = _crc64_table[(ord(char) ^ value) & 255] ^ value >> 8
            return value

        # original == 0 指未发原图，图片存于chatraw
        # original == 1 指发送原图，压缩后的图片存于chatimg,下载后原图存于chatraw
        folder = "chatimg" if original else "chatraw"
        raw_str = f"{folder}:{md5_candidates[0].upper()}"
        crc64_value = crc64(raw_str)
        file_name = f"Cache_{crc64_value:x}"
        legacy_path = source_path / folder / file_name[-3:] / file_name
        if legacy_path.is_file() and legacy_path.stat().st_size:
            output_path.mkdir(parents=True, exist_ok=True)
            destination = output_path / legacy_path.name
            if not destination.exists():
                shutil.copy2(legacy_path, destination)
            return destination

        return None

    @staticmethod
    def _get_md5_candidates(element):
        candidates = []
        raw_md5 = bytes(element.md5HexStr)
        if raw_md5:
            candidates.append(raw_md5.hex())
            try:
                candidates.append(raw_md5.decode('ascii'))
            except UnicodeDecodeError:
                pass
        candidates.extend([
            element.originImageMd5,
            element.fileName,
            element.imageFilePath,
            element.imageUrlOrigin,
        ])

        result = []
        for value in candidates:
            for match in re.findall(r'(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])', str(value)):
                normalized = match.lower()
                if normalized not in result:
                    result.append(normalized)
        return result

    @staticmethod
    @lru_cache(maxsize=8192)
    def _find_modern_cache_file(source_path, md5_value):
        return BaseImage._get_modern_cache_index(source_path).get(md5_value)

    @staticmethod
    @lru_cache(maxsize=4)
    def _get_modern_cache_index(source_path):
        if not source_path.is_dir():
            return {}

        candidates = {}
        for path in source_path.rglob('*'):
            if not path.is_file() or path.name.endswith('.tmp') or path.stat().st_size == 0:
                continue
            match = re.match(r'(?i)^([0-9a-f]{32})', path.name)
            if not match:
                continue
            md5_value = match.group(1).lower()
            current = candidates.get(md5_value)
            if current is None or BaseImage._cache_file_rank(path, md5_value) < BaseImage._cache_file_rank(current, md5_value):
                candidates[md5_value] = path
        return candidates

    @staticmethod
    def _cache_file_rank(path, md5_value):
        parts = {part.lower() for part in path.parts}
        return ('ori' not in parts, 'thumb' not in parts, path.stem.lower() != md5_value)

    def _get_content(self):
        pass


class BaseFile:
    def __init__(self, element):
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseVoice:
    def __init__(self, element):
        self.voice_text = element.voiceText
        self.voice_len = element.voiceLen
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)
        self.cache_path = self._export_voice_file(self.file_name)

        self.content = self._get_content()

    @staticmethod
    @lru_cache(maxsize=4096)
    def _export_voice_file(file_name):
        if not file_name or not voice_path:
            return None
        source = BaseVoice._get_voice_index(tuple(Path(path) for path in voice_source_paths)).get(
            Path(file_name).name.lower()
        )
        if source is None:
            return None

        destination_dir = Path(voice_path)
        destination_dir.mkdir(parents=True, exist_ok=True)
        suffix = '.silk' if BaseVoice._is_silk(source) else source.suffix.lower()
        destination = destination_dir / f'{source.stem}{suffix}'
        if destination.is_file() and destination.stat().st_size > 0:
            return destination

        shutil.copy2(source, destination)
        return destination

    @staticmethod
    @lru_cache(maxsize=4)
    def _get_voice_index(source_paths):
        index = {}
        for source_path in source_paths:
            if not source_path.is_dir():
                continue
            for path in source_path.rglob('*'):
                if path.is_file() and path.stat().st_size > 0:
                    index.setdefault(path.name.lower(), path)
        return index

    @staticmethod
    def _is_silk(path):
        with path.open('rb') as file:
            header = file.read(10)
        return header.startswith(b'#!SILK_V3') or header.startswith(b'\x02#!SILK_V3')

    def _get_content(self):
        pass


class BaseVideo:
    def __init__(self, element):
        self.formated_video_len = self._seconds_to_hms(element.videoLen)
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)
        self.path = element.videoPath

        self.content = self._get_content()

    @staticmethod
    def _seconds_to_hms(seconds):
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _get_content(self):
        pass


class BaseEmoji:
    def __init__(self, element):
        self.emoji_id = element.emojiId
        self.text = element.emojiText or emojis.get(self.emoji_id, "未知表情")

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseNotice:
    def __init__(self, element):
        self.info = element.noticeInfo
        self.info2 = element.noticeInfo2

        self.content = self._get_content()

    def _parse_info(self):
        if not self.info and not self.info2:
            return "[提示]", None
        elif self.info:
            self.info = self.info.replace(r'\/', '/').replace('\u3000', ' ')
            self.info = ''.join(char for char in self.info if category(char) not in ('Cf', 'Cc'))

            recover_parser = lxml_etree.XMLParser(recover=True)
            try:
                root = lxml_etree.fromstring(self.info)
            except lxml_etree.XMLSyntaxError:
                # 尝试使用恢复模式重新解析
                root = lxml_etree.fromstring(self.info.encode("utf-8"), parser=recover_parser)
            texts = [
                elem.get('txt')
                for elem in root.findall('.//nor')
                if elem.get('txt')
            ]
        elif self.info2:
            info2_dict = literal_eval(self.info2.replace(r"\/", "/"))
            texts = [item.get("txt", "")
                     for item
                     in info2_dict["items"]]

        return " ".join(texts)

    def _get_content(self):
        pass


class BaseRedPacket:
    def __init__(self, element):
        self.prompt = element.redPacket.prompt
        self.summary = element.redPacket.summary

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseApplication:
    def __init__(self, element):
        self.raw = element.applicationMessage

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseCall:
    def __init__(self, element):
        self.status = element.callStatus
        self.text = element.callText

        self.content = self._get_content()

    def _get_content(self):
        pass

class BaseFeed:
    def __init__(self, element):
        self.title = element.feedTitle.text
        self.feed_content = element.feedContent.text
        self.url = element.feedUrl

        self.content = self._get_content()

    def _get_content(self):
        pass
