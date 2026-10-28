import logging
import tomllib

from sys import argv
from pathlib import Path

import db
from exporter import base_elements
from exporter.json import JsonExportManager
from exporter.txt import TxtExportManager
from exporter.html import HtmlExportManager

logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

exporter_map = {
    "txt": TxtExportManager,
    "json": JsonExportManager,
    "html": HtmlExportManager
}


def mk_output_path(path, export_c2c=True, export_group=True):
    c2c_path = path / "c2c" if export_c2c else None
    group_path = path / "group" if export_group else None

    if c2c_path and not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if group_path and not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def run_single(task_type, queries, Exporter, path, dbman):
    logging.info(f"开始解析并写入{task_type}消息")
    Exporter(dbman,queries, path, task_type).process()

    logging.info(f"成功解析并写入{task_type}消息")


def main():
    config_path = Path(argv[1])
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    db_path = Path(config["db_path"])

    pic_path = Path(config["pic_path"])
    base_elements.pic_path = pic_path
    base_elements.pic_source_path = Path(config.get("pic_source_path", pic_path))
    base_elements.voice_source_paths = tuple(
        Path(path) for path in config.get("voice_source_paths", [])
    )

    if not config["output_path"]:
        output_path = Path(db_path).parent / "output"
    else:
        output_path = Path(config["output_path"])

    base_elements.voice_path = Path(config.get("voice_path", output_path / "chatvoice"))

    export_c2c = config.get("export_c2c", True)
    export_group = config.get("export_group", True)
    c2c_path, group_path = mk_output_path(output_path, export_c2c, export_group)

    c2c_filters = config["c2c_filters"]
    group_filters = config["group_filters"]

    dbman = db.DatabaseManager(db_path)

    c2c_queries = dbman.c2c_messages(c2c_filters) if export_c2c else None
    group_queries = dbman.group_messages(group_filters) if export_group else None

    for output_type in config["output_format"]:
        c2c_exporter = exporter_map[output_type]
        group_exporter = exporter_map[output_type]

        if export_c2c:
            run_single("c2c", c2c_queries, c2c_exporter, c2c_path, dbman)
        if export_group:
            run_single("group", group_queries, group_exporter, group_path, dbman)

        logging.info(f"成功导出{output_type}格式")


if __name__ == '__main__':
    main()
