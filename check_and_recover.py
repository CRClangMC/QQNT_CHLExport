#!/usr/bin/env python3
"""
检查并尝试恢复指定配置下的 SQLite .db 文件。
用法:
  python check_and_recover.py [config.toml]
默认读取项目同目录下的 `config.toml`。

脚本动作：
- 从 toml 中读取 `db_path`。
- 对目录下所有 `*.db` 执行 `PRAGMA integrity_check;`。
- 若检查不通过，会备份原文件为 `.bak`，并尝试用 Python 的 iterdump 导出并重建为 `*_recovered.db`。
- 不会自动替换原始文件，恢复成功后会打印新文件路径供你决定替换。
"""

import tomllib
import sqlite3
import glob
import os
import shutil
import sys
from pathlib import Path


def read_config(path: Path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def integrity_check(db_path: Path):
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchone()
        conn.close()
        return res
    except Exception as e:
        return (f"ERROR: {e}",)


def try_recover_iterdump(src: Path, dest: Path):
    # 备份由调用方负责
    try:
        src_conn = sqlite3.connect(str(src))
        dump_iter = src_conn.iterdump()
        # write to new DB
        dest_conn = sqlite3.connect(str(dest))
        script = []
        for line in dump_iter:
            script.append(line)
        if script:
            dest_conn.executescript("\n".join(script))
        dest_conn.close()
        src_conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    cfg_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.toml")
    if not cfg_file.exists():
        print("config.toml 未找到，请将配置文件路径作为参数传入。")
        sys.exit(2)

    cfg = read_config(cfg_file)
    db_path_raw = cfg.get("db_path")
    if not db_path_raw:
        print("config.toml 中未配置 db_path")
        sys.exit(2)

    db_dir = Path(db_path_raw)
    if not db_dir.is_absolute():
        db_dir = (cfg_file.parent / db_dir).resolve()

    if not db_dir.exists():
        print(f"db_path 指向的目录不存在: {db_dir}")
        sys.exit(2)

    print("检测目录:", db_dir)

    db_files = sorted(glob.glob(str(db_dir / "*.db")))
    if not db_files:
        print("未找到任何 .db 文件")
        sys.exit(0)

    for f in db_files:
        p = Path(f)
        print("\n--- Checking", p)
        res = integrity_check(p)
        print("  integrity_check:", res)
        if not res or (isinstance(res, tuple) and res[0] != "ok"):
            print("  -> 发现损坏或异常，尝试备份并恢复")
            bak = p.with_suffix(p.suffix + ".bak")
            try:
                shutil.copy2(p, bak)
                print("  备份到", bak)
            except Exception as e:
                print("  备份失败，跳过恢复：", e)
                continue

            recovered = p.with_name(p.stem + "_recovered.db")
            ok, err = try_recover_iterdump(p, recovered)
            if ok:
                print("  恢复完成 ->", recovered)
                chk = integrity_check(recovered)
                print("  恢复后 integrity_check:", chk)
                if chk and chk[0] == "ok":
                    print("  恢复文件已通过校验，你可以用 recovered 文件替换原文件（手动操作）")
                else:
                    print("  恢复后的文件仍未通过校验，建议尝试 sqlite3 CLI 的 .recover 或 GUI 工具")
            else:
                print("  基于 iterdump 的恢复失败：", err)
                print("  建议安装 sqlite3 CLI 后使用 '.recover'，或使用 DB Browser for SQLite 等工具")

    print("\n全部处理完成")


if __name__ == '__main__':
    main()
