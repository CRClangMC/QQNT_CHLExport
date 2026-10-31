#!/usr/bin/env python3
"""
自动化导出脚本：
用法示例:
    python auto_run_output.py -qq 你的QQ号 -lock_db_dir "你的数据库文件夹路径，一般在：你的QQ数据文件夹/QQ号/nt_qq/nt_db" -output_dir "输出文件夹" -c2c(私聊过滤器，示例: -c2c "[123456,654321]" 或 -c2c 123456,654321；不传或传空表示全部；-noc2c 表示不导出私聊) -group(群聊过滤器，示例: -group "[111,222]" 或 -group 111,222；不传或传空表示全部；-nogroup 表示不导出群聊) -format 格式，支持json/txt，逗号分隔

工作流：
 1. 调用 ./qq_dump_db/qq_dump_db.exe --qq <qq> --db-dir <lock_db_dir>
 2. 等待并定位 ./qq_dump_db/output/<qq>/ 目录中的数据库文件（例如 nt_msg.db）
 3. 调用 copy_tables_from_corrupt.py 修复数据库，生成 *_copied.db
 4. 备份原始文件为 nt_msg_original_corrupt.db，替换为 nt_msg_copied.db
 5. 根据传入参数生成并写入仓库根目录下的 config.toml
 6. 调用 python main.py ./config.toml 执行导出
"""
import argparse
import ast
import csv
import ctypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
import shutil
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def escape_toml_path(p: Path) -> str:
    # 将 Windows 路径写入 toml 时用双反斜线以保持与现有示例一致
    s = str(p)
    return s.replace('\\', '\\\\')


def run_cmd(cmd, cwd=None, check=True):
    logging.info('运行命令: %s', ' '.join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd, check=check)


def find_nt_msg_files(output_dir: Path):
    return list(output_dir.rglob('nt_msg.db'))


def key_map_has_nt_msg(key_map_path, source_db_dir):
    source_path = source_db_dir / 'nt_msg.db'
    try:
        with source_path.open('rb') as source:
            source.seek(1024)
            nt_msg_salt = source.read(16).hex()
        key_map = json.loads(key_map_path.read_text(encoding='utf-8')).get('key_map', {})
        return nt_msg_salt in key_map
    except (OSError, ValueError):
        return False


def is_process_running(pid):
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def is_plain_database(path):
    try:
        with path.open('rb') as database:
            return database.read(16) == b'SQLite format 3\x00'
    except OSError:
        return False


def decrypt_database(source_path, output_path, key, progress, resume=False):
    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    page_count = max(0, (source_path.stat().st_size - 1024) // 4096)
    completed_pages = 0
    if resume and temp_path.exists():
        temp_size = temp_path.stat().st_size
        completed_pages = min(temp_size // 4096, page_count)
        if completed_pages and not is_plain_database(temp_path):
            completed_pages = 0

    try:
        mode = 'r+b' if resume and temp_path.exists() else 'w+b'
        with source_path.open('rb') as source, temp_path.open(mode) as output:
            output.truncate(completed_pages * 4096)
            output.seek(completed_pages * 4096)
            source.seek(1024 + completed_pages * 4096)
            progress.update(completed_pages * 4096)
            page_number = completed_pages + 1
            while page := source.read(4096):
                if len(page) < 4096:
                    break
                skip = 16 if page_number == 1 else 0
                data = page[skip:]
                encrypted = data[:-48]
                iv = data[-48:-32]
                decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
                decrypted = decryptor.update(encrypted) + decryptor.finalize()

                if page_number == 1:
                    plain_page = bytearray(4096)
                    plain_page[:16] = b'SQLite format 3\x00'
                    plain_page[16:16 + len(decrypted)] = decrypted
                    plain_page[16:18] = (4096).to_bytes(2, 'big')
                    output.write(plain_page)
                else:
                    output.write(decrypted)
                    output.write(bytes(4096 - len(decrypted)))
                progress.update(4096)
                page_number += 1
        temp_path.replace(output_path)
        return True
    except (OSError, ValueError) as error:
        temp_path.unlink(missing_ok=True)
        tqdm.write(f'解密失败: {source_path.name}: {error}')
        return False


def required_database_names(export_c2c, export_group):
    required = {'nt_msg.db'}
    if export_c2c:
        required.add('profile_info.db')
    if export_group:
        required.add('group_info.db')
    return required


def decrypt_databases(
    key_map_path,
    source_db_dir,
    dump_output_dir,
    export_c2c=True,
    export_group=True,
    resume=False,
):
    key_map = json.loads(key_map_path.read_text(encoding='utf-8')).get('key_map', {})
    required_names = required_database_names(export_c2c, export_group)
    jobs = []
    for source_path in source_db_dir.rglob('*.db'):
        if source_path.name not in required_names:
            continue
        try:
            with source_path.open('rb') as source:
                source.seek(1024)
                salt = source.read(16).hex()
        except OSError:
            continue
        if salt in key_map:
            page_bytes = max(0, (source_path.stat().st_size - 1024) // 4096 * 4096)
            jobs.append((source_path, bytes.fromhex(key_map[salt]), page_bytes))

    total_bytes = sum(page_bytes for _, _, page_bytes in jobs)
    succeeded = 0
    with tqdm(
        total=total_bytes,
        desc='解密数据库',
        unit='B',
        unit_scale=True,
        unit_divisor=1024,
        leave=False,
    ) as progress:
        for source_path, key, page_bytes in jobs:
            output_path = dump_output_dir / source_path.name
            position_before = progress.n
            if resume and is_plain_database(output_path):
                progress.update(page_bytes)
                succeeded += 1
            elif decrypt_database(source_path, output_path, key, progress, resume):
                succeeded += 1
            missing_bytes = page_bytes - (progress.n - position_before)
            if missing_bytes > 0:
                progress.update(missing_bytes)
    return succeeded, len(jobs)


def run_qq_dump(
    cmd,
    pid,
    cwd,
    dump_output_dir,
    source_db_dir,
    on_confirmed,
    export_c2c=True,
    export_group=True,
    resume=False,
):
    output_lines = []
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
    )

    def collect_output():
        for line in process.stdout:
            output_lines.append(line)

    output_thread = threading.Thread(target=collect_output, daemon=True)
    output_thread.start()
    target_was_running = True
    close_prompt_shown = False
    while process.poll() is None:
        key_map_path = dump_output_dir / 'key_map.json'
        if not close_prompt_shown and key_map_has_nt_msg(key_map_path, source_db_dir):
            close_prompt_shown = True
            on_confirmed()
            tqdm.write('已确认 QQ 主进程，请关闭 QQ。')
        if target_was_running and not is_process_running(pid):
            target_was_running = False
            logging.info('目标 QQ 进程 PID %d 已退出，继续解密数据库', pid)
            process.terminate()
            break
        time.sleep(0.5)
    returncode = process.wait()
    output_thread.join()
    key_map_path = dump_output_dir / 'key_map.json'
    if close_prompt_shown and key_map_path.exists():
        time.sleep(1)
        succeeded, total = decrypt_databases(
            key_map_path,
            source_db_dir,
            dump_output_dir,
            export_c2c,
            export_group,
            resume,
        )
        logging.info('Python 流式解密完成: %d/%d 个数据库', succeeded, total)
        returncode = 0 if is_plain_database(dump_output_dir / 'nt_msg.db') else 1
    return returncode, ''.join(output_lines)


def database_log(output):
    marker = '========================================================================\nRESULTS:'
    marker_index = output.find(marker)
    if marker_index < 0:
        return output.strip()
    return output[marker_index:].strip()


def find_qq_main_pids():
    try:
        qq_result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq QQ.exe', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
            errors='replace',
            check=False,
        )
        module_result = subprocess.run(
            ['tasklist', '/M', 'wrapper.node', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
            errors='replace',
            check=False,
        )

        memory_by_pid = {}
        for row in csv.reader(qq_result.stdout.splitlines()):
            if len(row) < 5 or row[0].lower() != 'qq.exe' or not row[1].isdigit():
                continue
            memory_by_pid[int(row[1])] = int(''.join(char for char in row[4] if char.isdigit()) or 0)

        wrapper_pids = set()
        for row in csv.reader(module_result.stdout.splitlines()):
            if len(row) >= 2 and row[0].lower() == 'qq.exe' and row[1].isdigit():
                wrapper_pids.add(int(row[1]))

        candidates = wrapper_pids or set(memory_by_pid)
        return sorted(candidates, key=lambda pid: memory_by_pid.get(pid, 0), reverse=True)
    except OSError:
        return []


def main():
    parser = argparse.ArgumentParser(description='自动运行导出流程')
    parser.add_argument('-qq', required=True, help='QQ号')
    parser.add_argument('-lock_db_dir', required=True, help='原始数据库路径（支持 E:\\path 或 E:/path，qq_dump_db 的 --db-dir）')
    parser.add_argument('-output_dir', required=True, help='导出路径（写入 config.toml 的 output_path）')
    parser.add_argument('-keeptemp', action='store_true', help='保留解密临时目录和自动生成的 config.toml')
    parser.add_argument(
        '-continue',
        '--continue',
        dest='continue_run',
        action='store_true',
        help='从上次中断处继续，复用已解密数据库并从临时分页文件恢复',
    )
    c2c_group = parser.add_mutually_exclusive_group()
    c2c_group.add_argument('-c2c', nargs='?', const='[]', default=None,
                           help='私聊过滤器，示例: -c2c "[123456,654321]" 或 -c2c 123456,654321；不传或传空表示全部')
    c2c_group.add_argument('-noc2c', action='store_true', help='不导出私聊记录')
    group_group = parser.add_mutually_exclusive_group()
    group_group.add_argument('-group', nargs='?', const='[]', default=None,
                             help='群聊过滤器，示例: -group "[111,222]" 或 -group 111,222；不传或传空表示全部')
    group_group.add_argument('-nogroup', action='store_true', help='不导出群聊记录')
    parser.add_argument('-format', required=True, help='导出格式，逗号分隔（如 json 或 txt,json）')
    args = parser.parse_args()

    repo_root = Path(__file__).parent.resolve()

    qq = args.qq
    lock_db_dir = Path(args.lock_db_dir)
    output_dir = Path(args.output_dir).resolve()
    formats = [f.strip() for f in args.format.split(',') if f.strip()]

    def parse_filter_arg(val):
        # 返回列表（可能为空），支持多种输入格式
        if val is None:
            return []
        s = str(val).strip()
        if s == '[]' or s == '':
            return []
        # 尝试解析为 Python 列表文字
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        except Exception:
            pass
        # 否则按逗号分割
        parts = [p.strip() for p in s.split(',') if p.strip()]
        return parts

    c2c_filters_arg = parse_filter_arg(args.c2c)
    group_filters_arg = parse_filter_arg(args.group)
    export_c2c = not args.noc2c
    export_group = not args.nogroup

    if not export_c2c and not export_group:
        parser.error('-noc2c 和 -nogroup 不能同时使用')

    # 1. 调用 qq_dump_db.exe
    qq_dump_exe = repo_root / 'qq_dump_db' / ('qq_dump_db.exe')
    if not qq_dump_exe.exists():
        logging.error('找不到 qq_dump_db 可执行文件: %s', qq_dump_exe)
        raise SystemExit(2)

    dump_output_dir = repo_root / 'output' / qq
    key_map_path = dump_output_dir / 'key_map.json'
    possible_dump_dirs = [
        repo_root / 'qq_dump_db' / 'output' / qq,
        dump_output_dir,
        output_dir / qq,
    ]
    logging.info('解密数据库输出目录: %s', ', '.join(map(str, possible_dump_dirs)))
    nt_files = []
    required_names = required_database_names(export_c2c, export_group)
    if args.continue_run:
        if key_map_path.exists() and key_map_has_nt_msg(key_map_path, lock_db_dir):
            succeeded, total = decrypt_databases(
                key_map_path,
                lock_db_dir,
                dump_output_dir,
                export_c2c,
                export_group,
                resume=True,
            )
            logging.info('续跑解密完成: %d/%d 个数据库', succeeded, total)
        cached_databases_ready = all(
            is_plain_database(dump_output_dir / name)
            for name in required_names
        )
        if cached_databases_ready:
            nt_files = find_nt_msg_files(dump_output_dir)
            logging.info('已找到可续用的解密数据库，无需重新提取密钥')

    qq_main_pids = [] if nt_files else find_qq_main_pids()
    if not nt_files and not qq_main_pids:
        print('Please run QQ or use -continue with complete cached databases.', file=sys.stderr)
        raise SystemExit(1)

    with tqdm(
        total=len(qq_main_pids),
        desc='自动确认 QQ 主进程',
        unit='个',
        leave=False,
    ) as pid_progress:
        for pid in qq_main_pids:
            if dump_output_dir.exists() and not args.continue_run:
                shutil.rmtree(dump_output_dir)

            cmd = [
                str(qq_dump_exe), '--qq', qq, '--pid', str(pid),
                '--db-dir', str(lock_db_dir),
            ]
            dump_started_at = time.time()
            pid_confirmed = False

            def mark_pid_confirmed():
                nonlocal pid_confirmed
                pid_confirmed = True
                pid_progress.n = pid_progress.total
                pid_progress.refresh()
                pid_progress.close()

            _, qq_dump_output = run_qq_dump(
                cmd,
                pid,
                repo_root,
                dump_output_dir,
                lock_db_dir,
                mark_pid_confirmed,
                export_c2c,
                export_group,
                args.continue_run,
            )
            if not pid_confirmed:
                pid_progress.update(1)
            nt_files = [
                path for path in find_nt_msg_files(dump_output_dir)
                if is_plain_database(path)
                and (args.continue_run or path.stat().st_mtime >= dump_started_at - 1)
            ]
            if nt_files:
                print(database_log(qq_dump_output), flush=True)
                logging.info('已从 QQ 进程 PID %d 提取数据库密钥', pid)
                break

    # 2. 只接受本次解密新生成的数据库，禁止复用上次残留产物
    if not nt_files:
        print('数据库解密失败：已尝试全部 QQ 主进程，仍未生成 nt_msg.db，请检查是否打开QQ', file=sys.stderr)
        raise SystemExit(4)
    logging.info('本次解密数据库目录: %s', dump_output_dir)

    # 3. 对每个找到的 nt_msg.db 执行修复脚本并替换
    for nt in nt_files:
        logging.info('处理数据库: %s', nt)
        logging.info('正在从解密数据库恢复可读聊天记录并重建数据库。')
        repair_cmd = [sys.executable, str(repo_root / 'copy_tables_from_corrupt.py'), str(nt)]
        if not export_c2c:
            repair_cmd.append('--skip-c2c')
        if not export_group:
            repair_cmd.append('--skip-group')
        if export_group and group_filters_arg:
            repair_cmd.extend(['--groups', ','.join(map(str, group_filters_arg))])
        try:
            run_cmd(repair_cmd, cwd=repo_root)
        except subprocess.CalledProcessError:
            logging.error('copy_tables_from_corrupt.py 失败，已停止以避免使用不完整数据库: %s', nt)
            raise

        copied = nt.with_name(nt.stem + '_copied' + nt.suffix)
        if not copied.exists():
            logging.error('修复后文件不存在: %s', copied)
            continue

        # 4. 备份原始并替换
        original_backup = nt.with_name(nt.stem + '_original_corrupt' + nt.suffix)
        logging.info('备份 %s -> %s', nt, original_backup)
        shutil.copy2(nt, original_backup)

        logging.info('用 %s 替换 %s', copied, nt)
        # 覆盖原文件
        shutil.copy2(copied, nt)
        logging.info('替换完成')

    # 5. 生成 config.toml
    # 确保输出路径和 pic_path 存在
    output_dir.mkdir(parents=True, exist_ok=True)
    pic_path = output_dir / 'chatpic'
    pic_path.mkdir(parents=True, exist_ok=True)
    pic_source_path = lock_db_dir.parent / 'nt_data' / 'Pic'
    voice_path = output_dir / 'chatvoice'
    voice_source_paths = [
        lock_db_dir.parent / 'nt_data' / 'Ptt',
        lock_db_dir.parents[1] / 'Audio',
    ]

    config_path = repo_root / 'config.toml'
    toml_lines = []
    toml_lines.append('# 自动生成的 config.toml，由 auto_run_output.py 创建')
    toml_lines.append('')
    toml_lines.append('# 解密后的数据库目录路径')
    toml_lines.append(f'db_path = "{escape_toml_path(dump_output_dir)}"')
    toml_lines.append('')
    toml_lines.append('# chatpic目录路径')
    toml_lines.append(f'pic_path = "{escape_toml_path(pic_path)}"')
    toml_lines.append(f'pic_source_path = "{escape_toml_path(pic_source_path)}"')
    toml_lines.append(f'voice_path = "{escape_toml_path(voice_path)}"')
    voice_sources = ','.join(f'"{escape_toml_path(path)}"' for path in voice_source_paths)
    toml_lines.append(f'voice_source_paths = [{voice_sources}]')
    toml_lines.append('')
    toml_lines.append('# 导出路径')
    toml_lines.append(f'output_path = "{escape_toml_path(output_dir)}"')
    toml_lines.append('')
    # c2c/group filters
    toml_lines.append('# c2c_filters: 为空数组表示导出全部私聊；可填写 QQ 列表')
    def fmt_filter_list(items):
        # 将 items 转为 toml 列表表示，数字不加引号
        out = []
        for it in items:
            try:
                out.append(str(int(it)))
            except Exception:
                out.append(f'"{str(it)}"')
        return '[' + ','.join(out) + ']'

    toml_lines.append(f'c2c_filters = {fmt_filter_list(c2c_filters_arg)}')
    toml_lines.append(f'export_c2c = {str(export_c2c).lower()}')
    toml_lines.append('')
    toml_lines.append('# group_filters: 为空数组表示导出全部群聊；可填写 群号 列表')
    toml_lines.append(f'group_filters = {fmt_filter_list(group_filters_arg)}')
    toml_lines.append(f'export_group = {str(export_group).lower()}')
    toml_lines.append('')
    # 输出格式
    fmt_list = ','.join([f'"{f}"' for f in formats])
    toml_lines.append('# 需要导出的文件格式')
    toml_lines.append(f'output_format = [{fmt_list}]')

    logging.info('写入配置文件: %s', config_path)
    config_path.write_text('\n'.join(toml_lines), encoding='utf-8')

    # 6. 运行 main.py
    try:
        run_cmd([sys.executable, str(repo_root / 'main.py'), str(config_path)], cwd=repo_root)
    except subprocess.CalledProcessError as e:
        logging.error('运行 main.py 导出失败: %s', e)
        raise

    logging.info('全部流程完成，导出文件位于: %s', output_dir)

    # 清理临时输出目录和生成的 config.toml
    if args.keeptemp:
        logging.info('已保留临时输出目录和配置文件')
    else:
        try:
            if dump_output_dir and dump_output_dir.exists():
                logging.info('删除临时输出目录: %s', dump_output_dir)
                shutil.rmtree(dump_output_dir)
            if config_path.exists():
                logging.info('删除临时配置文件: %s', config_path)
                config_path.unlink()
        except Exception as e:
            logging.warning('清理失败: %s', e)


if __name__ == '__main__':
    main()
