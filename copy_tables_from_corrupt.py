#!/usr/bin/env python3
"""
从损坏的 SQLite 数据库复制关键表到新数据库（不复制索引），以绕过索引损坏问题。
用法:
  python copy_tables_from_corrupt.py <source_db_path> [<new_db_path>]
如果不指定 new_db_path，会在同目录创建 `<source>_copied.db`。

注意：先备份原文件。该脚本只复制表结构和表数据，不复制索引与触发器。
"""
import sqlite3
import sys
import argparse
from pathlib import Path
import shutil
from tqdm import tqdm

KEY_TABLES = [
    'c2c_msg_table',
    'group_msg_table',
    'nt_uid_mapping_table',
    'profile_info_v6',
    'group_list',
    'group_member3',
]


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def copy_rows_by_rowid(src: Path, conn, cur, table: str, row_filter=None,
                       batch_size=500, skip_size=32):
    quoted_table = quote_identifier(table)
    source_conn = sqlite3.connect(str(src))
    indexes = source_conn.execute(f'PRAGMA index_list({quoted_table})').fetchall()
    if not indexes:
        source_conn.close()
        raise RuntimeError(f'{table} 没有可用于恢复 rowid 的索引')
    index_name = quote_identifier(indexes[0][1])
    where_sql, where_params = row_filter or ('', ())
    rowid_cursor = source_conn.execute(
        f'SELECT rowid FROM {quoted_table} INDEXED BY {index_name} {where_sql}',
        where_params,
    )
    try:
        total_rows = source_conn.execute(
            f'SELECT COUNT(rowid) FROM {quoted_table} INDEXED BY {index_name} {where_sql}',
            where_params,
        ).fetchone()[0]
    except sqlite3.DatabaseError:
        total_rows = None
    copied_rows = 0
    skipped_rowids = []

    def copy_batch(rowids):
        nonlocal copied_rows
        placeholders = ','.join('?' for _ in rowids)
        try:
            rows = source_conn.execute(
                f'SELECT * FROM {quoted_table} NOT INDEXED '
                f'WHERE rowid IN ({placeholders})',
                rowids,
            ).fetchall()
            if rows:
                value_placeholders = ','.join('?' for _ in rows[0])
                cur.executemany(
                    f'INSERT INTO {quoted_table} VALUES ({value_placeholders})',
                    rows,
                )
                conn.commit()
                copied_rows += len(rows)
            if len(rows) != len(rowids):
                recovered_ids = {row[0] for row in rows}
                skipped_rowids.extend(rowid for rowid in rowids if rowid not in recovered_ids)
        except sqlite3.DatabaseError:
            conn.rollback()
            if len(rowids) <= skip_size:
                skipped_rowids.extend(rowids)
                return
            middle = len(rowids) // 2
            copy_batch(rowids[:middle])
            copy_batch(rowids[middle:])

    with tqdm(total=total_rows, desc=f'分段恢复 {table}', unit='行') as progress:
        while True:
            rowids = [row[0] for row in rowid_cursor.fetchmany(batch_size)]
            if not rowids:
                break
            copy_batch(rowids)
            progress.update(len(rowids))

    source_conn.close()
    return copied_rows, skipped_rowids


def copy_table_in_batches(conn, cur, table, row_filter=None, batch_size=1000):
    quoted_table = quote_identifier(table)
    where_sql, where_params = row_filter or ('', ())
    total_rows = cur.execute(
        f'SELECT COUNT(*) FROM old.{quoted_table} {where_sql}',
        where_params,
    ).fetchone()[0]
    source_cursor = cur.execute(
        f'SELECT * FROM old.{quoted_table} {where_sql}',
        where_params,
    )
    copied_rows = 0
    with tqdm(total=total_rows, desc=f'复制 {table}', unit='行') as progress:
        while True:
            rows = source_cursor.fetchmany(batch_size)
            if not rows:
                break
            value_placeholders = ','.join('?' for _ in rows[0])
            conn.executemany(
                f'INSERT INTO {quoted_table} VALUES ({value_placeholders})',
                rows,
            )
            copied_rows += len(rows)
            progress.update(len(rows))
        conn.commit()
    return copied_rows


def copy_tables(src: Path, dest: Path, tables=None, group_filters=None):
    if tables is None:
        tables = KEY_TABLES
    if not src.exists():
        raise SystemExit("源数据库不存在")
    # backup source
    bak = src.with_suffix(src.suffix + '.bak')
    if not bak.exists():
        shutil.copy2(src, bak)

    if dest.exists():
        dest.unlink()

    conn = sqlite3.connect(str(dest))
    cur = conn.cursor()
    # attach old db as 'old'
    cur.execute("ATTACH DATABASE ? AS old", (str(src),))

    # fetch available table names in old
    old_tables = set(r[0] for r in cur.execute("SELECT name FROM old.sqlite_master WHERE type='table'").fetchall())
    failed_tables = []
    recovered_rows = 0
    skipped_rows = 0
    group_row_filter = None
    if group_filters:
        placeholders = ','.join('?' for _ in group_filters)
        group_row_filter = (
            f'WHERE "40027" IN ({placeholders})',
            tuple(int(group_num) for group_num in group_filters),
        )

    for t in tables:
        if t not in old_tables:
            continue
        try:
            # get create sql from old
            row = cur.execute("SELECT sql FROM old.sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            create_sql = row[0] if row else None
            if create_sql:
                # remove AUTOINCREMENT references to avoid sqlite_sequence issues
                cur.execute(create_sql)
            else:
                # fallback: create table by selecting zero rows (infer columns)
                cur.execute(f"CREATE TABLE \"{t}\" AS SELECT * FROM old.\"{t}\" WHERE 0")
            row_filter = group_row_filter if t == 'group_msg_table' else None
            copy_table_in_batches(conn, cur, t, row_filter)
        except Exception:
            conn.rollback()
            try:
                row_filter = group_row_filter if t == 'group_msg_table' else None
                cur.execute(f'DELETE FROM {quote_identifier(t)}')
                conn.commit()
                tqdm.write(f'{t} 存在损坏，正在按索引分段恢复可读记录。')
                copied_rows, skipped_rowids = copy_rows_by_rowid(src, conn, cur, t, row_filter)
                recovered_rows += copied_rows
                skipped_rows += len(skipped_rowids)
                if copied_rows == 0:
                    failed_tables.append(t)
            except Exception as recover_error:
                print(f"错误：{t} 分段恢复失败: {recover_error}", file=sys.stderr)
                failed_tables.append(t)

    # detach
    cur.execute("DETACH DATABASE old")
    # integrity check
    try:
        res = conn.execute("PRAGMA integrity_check;").fetchone()
    except Exception as e:
        conn.close()
        raise RuntimeError(f"完整性检查失败: {e}") from e
    conn.close()

    if failed_tables:
        raise RuntimeError(f"关键表复制失败: {', '.join(failed_tables)}")
    if not res or res[0] != "ok":
        raise RuntimeError(f"完整性检查未通过: {res}")

    summary = f"全部完成，修复数据库已生成: {dest}"
    if recovered_rows or skipped_rows:
        summary += f"（从损坏表恢复 {recovered_rows} 行，跳过 {skipped_rows} 行）"
    print(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source_db_path')
    parser.add_argument('new_db_path', nargs='?')
    parser.add_argument('--skip-c2c', action='store_true')
    parser.add_argument('--groups', help='仅恢复指定群号，逗号分隔')
    args = parser.parse_args()

    src = Path(args.source_db_path)
    dest = Path(args.new_db_path) if args.new_db_path else src.with_name(src.stem + "_copied.db")
    tables = [table for table in KEY_TABLES if not args.skip_c2c or table != 'c2c_msg_table']
    group_filters = args.groups.split(',') if args.groups else None
    copy_tables(src, dest, tables, group_filters)
