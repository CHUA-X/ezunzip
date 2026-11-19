#!/usr/bin/python3
# 一键解压神器 ——人性化一键解压缩体验
"""
用法：
    python 一键解压神器.py                                 ——> 弹窗（无pymsgbox则命令行提升）选择目录
    python 一键解压神器.py <路径>                          ——> 直接处理指定目录
    python 一键解压神器.py <路径> --dry-run                ——> 只列出计划，不动文件
    python 一键解压神器.py <路径> --recursive --overwrite  ——> 递归处理文件，且若有重复文件则覆盖
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import tarfile
import zipfile
import argparse
import platform
import traceback
import subprocess
from pathlib import Path
from dataclasses import dataclass, field

APP_NAME = '一键解压神器'
OUTPUT_DIR = '已解压文件'
CONFIG_NAME = 'config.conf'
LOG_NAME = '日志.log'

# 后缀列表
SUFFIXES = (
    '.tar.gz', '.tar.bz2', '.tar.xz',
    '.tgz', '.tbz2', '.txz',
    '.zip', '.rar', '.7z', '.tar', '.cab',
)

IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'


# 异常

class ArchiveError(Exception):
    """解压过程中的可预期错误"""


class UnsafeArchive(ArchiveError):
    """压缩包内有越界路径或符号链接则拒绝解压"""


class MissingDependency(ArchiveError):
    """缺少处理该格式所需的第三方库或外部程序"""


# 辅助函数

def human_size(size: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f}{unit}' if unit == 'B' else f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}TB'


def match_suffix(path: Path) -> str | None:
    """返回命中的压缩包后缀（小写），不是压缩包则返回 None"""
    name = path.name.lower()
    hits = [s for s in SUFFIXES if name.endswith(s) and len(name) > len(s)]
    return max(hits, key=len) if hits else None


def target_name(path: Path, suffix: str) -> str:
    """从文件名去掉压缩包后缀，得到解压目标目录名"""
    stripped = path.name[: -len(suffix)]
    return stripped or '未命名压缩包'


def is_safe_member(name: str) -> bool:
    """判断压缩包内成员路径是否安全（防止 ../ 与绝对路径越界写入）"""
    if not name:
        return False
    normalized = name.replace('\\', '/')
    if normalized.startswith('/'):
        return False
    if re.match(r'^[A-Za-z]:', normalized):
        return False
    parts = [part for part in normalized.split('/') if part not in ('', '.')]
    return '..' not in parts


def ensure_safe_members(names, archive: Path) -> None:
    for name in names:
        if not is_safe_member(name):
            raise UnsafeArchive(f'压缩包内含越界路径，已拒绝解压：{name}')


def find_7z() -> str | None:
    """定位7-Zip可执行文件"""
    for exe in ('7z', '7zz', '7za'):
        found = shutil.which(exe)
        if found:
            return found
    if IS_WINDOWS:
        for base in (r'C:\Program Files\7-Zip\7z.exe',
                     r'C:\Program Files (x86)\7-Zip\7z.exe'):
            if Path(base).is_file():
                return base
    return None


def check_free_space(dest: Path, needed: int) -> None:
    if needed <= 0:
        return
    probe = dest
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if needed > free:
        raise ArchiveError(
            f'空间不足：需要约{human_size(needed)}，目标盘仅剩{human_size(free)}'
        )


# 各格式解压后端

def extract_zip(src: Path, dest: Path) -> int:
    """解压ZIP：手动逐条写入，以便修正中文文件名乱码并拦截越界路径"""
    count = 0
    with zipfile.ZipFile(src) as archive:
        infos = archive.infolist()
        ensure_safe_members((decode_zip_name(info) for info in infos), src)
        total = sum(info.file_size for info in infos if not info.is_dir())
        check_free_space(dest, total)

        for info in infos:
            name = decode_zip_name(info)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                continue
            out_path = dest / name
            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(out_path, 'wb') as sink:
                shutil.copyfileobj(source, sink)
            count += 1
    return count


def decode_zip_name(info: zipfile.ZipInfo) -> str:
    """Windows 下大量老ZIP用GBK存文件名且不设UTF-8标志位。
    zipfile会按cp437解码，得到乱码，因此还原字节后依次尝试utf-8或gbk。
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode('cp437')
    except UnicodeEncodeError:
        return name
    for encoding in ('utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


def decode_tar_name(name: str) -> str:
    """老工具（老版WinRAR、7-Zip、GNU tar等）的tar用GBK存文件名。
    tar没有编码标志位，tarfile默认按UTF-8读，遇到GBK字节会用
    surrogateescape特性把每个非法字节记成“\\udcXX”代理字符，解出来
    是乱码文件。代理字符与原始字节一一对应、可逆，所以这里
    encode还原出原始字节，再依次尝试utf-8或gbk
    """
    if not any('\udc80' <= ch <= '\udcff' for ch in name):
        return name
    raw = name.encode('utf-8', errors='surrogateescape')
    for encoding in ('utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


def extract_tar(src: Path, dest: Path) -> int:
    """解压tar系列（tar、tar.gz、tar.bz2、tar.xz等）"""
    count = 0
    with tarfile.open(src, 'r:*') as archive:
        members = archive.getmembers()
        usable = [m for m in members
                  if not (m.issym() or m.islnk() or m.isdev() or m.isfifo())]
        total = sum(m.size for m in usable if m.isfile())
        check_free_space(dest, total)

        for member in usable:
            fixed = decode_tar_name(member.name)
            ensure_safe_members((fixed,), src)
            if member.isdir():
                (dest / fixed).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            out_path = dest / fixed
            out_path.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, open(out_path, 'wb') as sink:
                shutil.copyfileobj(source, sink)
            count += 1
    return count


def extract_7z(src: Path, dest: Path) -> int:
    try:
        import py7zr
    except ImportError:
        raise MissingDependency('解压 .7z 需要 py7zr：pip install py7zr')

    with py7zr.SevenZipFile(src) as archive:
        names = archive.getnames()
        ensure_safe_members(names, src)
        try:
            archive.extractall(path=dest)
        except Exception as err:
            text = str(err)
            if 'password' in text.lower() or 'encrypt' in text.lower():
                raise ArchiveError('压缩包已加密，需要密码，已跳过') from err
            raise
    return sum(1 for name in names if not name.replace('\\', '/').endswith('/'))


def extract_rar(src: Path, dest: Path) -> int:
    try:
        import rarfile
    except ImportError:
        raise MissingDependency('解压RAR需要rarfile模块\n请使用“pip install rarfile”安装。')

    seven = find_7z()
    if seven:
        rarfile.SEVENZIP_TOOL = seven
        try:
            rarfile.tool_setup(force=True)
        except Exception:
            pass

    try:
        archive = rarfile.RarFile(src)
    except rarfile.RarCannotExec as err:
        raise MissingDependency('解压RAR需要unrar、7-Zip和bsdtar其中之一，当前都没找到哦') from err

    with archive:
        infos = archive.infolist()
        ensure_safe_members((info.filename for info in infos), src)
        members = [info for info in infos if not _rar_is_symlink(info)]
        total = sum(info.file_size for info in members if not info.isdir())
        check_free_space(dest, total)
        try:
            archive.extractall(path=dest, members=members)
        except Exception as err:
            if _is_password_error(err):
                raise ArchiveError('压缩包已加密，需要密码，已跳过') from err
            raise
    return sum(1 for info in members if not info.isdir())


def _rar_is_symlink(info) -> bool:
    checker = getattr(info, 'is_symlink', None)
    return bool(checker()) if callable(checker) else False


def _is_password_error(err: Exception) -> bool:
    name = type(err).__name__
    if 'Password' in name or 'NeedFirstVolume' in name:
        return True
    return 'password' in str(err).lower()


def extract_cab(src: Path, dest: Path) -> int:
    """解压CAB，只用7-Zip命令行"""
    seven = find_7z()
    if not seven:
        raise MissingDependency(
            '解压CAB需要7-Zip，但系统里没找到。\n'
            '请安装7-Zip（https://7-zip.org）后重试。'
        )
    return _extract_cab_by_7z(seven, src, dest)


def _extract_cab_by_7z(seven: str, src: Path, dest: Path) -> int:
    listing = run_7z([seven, 'l', '-slt', '-ba', '-sccUTF-8', str(src)], '列出压缩包内容')
    names = []
    for line in listing.splitlines():
        if line.startswith('Path = '):
            names.append(line[len('Path = '):])
    ensure_safe_members(names, src)
    run_7z([seven, 'x', '-y', '-sccUTF-8', f'-o{dest}', str(src)], '解压压缩包')
    return len(names)


def run_7z(args, action: str) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=600)
    except FileNotFoundError as err:
        raise MissingDependency(f'调用7-Zip失败：{err}') from err
    except subprocess.TimeoutExpired as err:
        raise ArchiveError(f'{action}超时（超过 10 分钟）') from err

    stdout = (proc.stdout or b'').decode('utf-8', errors='replace')
    if proc.returncode != 0:
        stderr = (proc.stderr or b'').decode('utf-8', errors='replace').strip()
        if not stderr:
            tail = stdout.strip().splitlines()
            stderr = tail[-1] if tail else '无输出'
        raise ArchiveError(f'{action}失败（7-Zip返回{proc.returncode}）：{stderr}')
    return stdout


EXTRACTORS = {
    '.zip': extract_zip,
    '.rar': extract_rar,
    '.7z': extract_7z,
    '.cab': extract_cab,
    '.tar': extract_tar,
    '.tar.gz': extract_tar,
    '.tar.bz2': extract_tar,
    '.tar.xz': extract_tar,
    '.tgz': extract_tar,
    '.tbz2': extract_tar,
    '.txz': extract_tar,
}


# 批处理

@dataclass
class Result:
    source: Path
    status: str
    detail: str = ''
    files: int = 0
    target: Path | None = None


@dataclass
class Summary:
    results: list = field(default_factory=list)

    def add(self, result: Result) -> None:
        self.results.append(result)

    def count(self, status: str) -> int:
        return sum(1 for item in self.results if item.status == status)

    @property
    def handled(self) -> int:
        return len(self.results)


def collect_archives(work_dir: Path, out_dir: Path, recursive: bool):
    """列出待处理的压缩包，跳过符号链接与输出目录内部的文件"""
    iterator = work_dir.rglob('*') if recursive else work_dir.iterdir()
    archives = []
    for path in iterator:
        try:
            if out_dir == path or out_dir in path.parents:
                continue
            if not path.is_file() or path.is_symlink():
                continue
        except OSError:
            continue
        suffix = match_suffix(path)
        if suffix:
            archives.append((path, suffix))
    archives.sort(key=lambda item: str(item[0]).lower())
    return archives


def target_exists_with_content(target: Path) -> bool:
    """判断目标目录是否已经有相关已解压文件"""
    if not target.is_dir():
        return False
    try:
        return any(target.iterdir())
    except OSError:
        return False


def process_one(path: Path, suffix: str, out_dir: Path,
                overwrite: bool, dry_run: bool) -> Result:
    target = out_dir / target_name(path, suffix)
    already = target_exists_with_content(target)

    if already and not overwrite:
        return Result(path, 'skipped', f'目标已存在：{target.name}', target=target)

    if dry_run:
        if already:
            return Result(path, 'planned', f'合并写入{target.name}', target=target)
        return Result(path, 'planned', f'→{target.name}', target=target)

    try:
        target.mkdir(parents=True, exist_ok=True)
        count = EXTRACTORS[suffix](path, target)
        return Result(path, 'ok', f'{count} 个文件', files=count, target=target)
    except ArchiveError as err:
        _drop_if_empty(target)
        return Result(path, 'failed', str(err), target=target)
    except Exception as err:  # 兜底：库内部异常五花八门，统一记账
        _drop_if_empty(target)
        return Result(path, 'failed', f'{type(err).__name__}: {err}', target=target)


def _drop_if_empty(target: Path) -> None:
    """解压失败后清掉空目录防止报错"""
    try:
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
    except OSError:
        pass


def write_log(work_dir: Path, summary: Summary) -> Path | None:
    """失败时写日志"""
    failures = [item for item in summary.results if item.status == 'failed']
    if not failures:
        return None
    lines = [f'{APP_NAME} 运行记录']
    for item in failures:
        lines.extend(['', f'[失败]{item.source}', f'  原因：{item.detail}'])
    log_path = work_dir / LOG_NAME
    try:
        log_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError:
        return None
    return log_path


def describe(summary: Summary) -> str:
    ok = summary.count('ok')
    skipped = summary.count('skipped')
    failed = summary.count('failed')
    planned = summary.count('planned')
    parts = []
    if planned:
        parts.append(f'待解压{planned}个')
    if ok:
        parts.append(f'成功{ok}个')
    if skipped:
        parts.append(f'跳过{skipped}个（目标已存在）')
    if failed:
        parts.append(f'失败{failed}个')
    return '，'.join(parts) if parts else '没有可解压的压缩包'


# GUI交互

def require_gui():
    try:
        import pymsgbox
    except ImportError:
        return None
    return pymsgbox


def ask(prompt: str, title: str, gui) -> str | None:
    """弹窗或命令行参数读取输入；返回None表示被取消"""
    if gui:
        return gui.prompt(prompt, title)
    print(prompt)
    try:
        text = input('>>')
    except EOFError:
        return None
    return text


def notify(message: str, title: str, gui) -> None:
    if gui:
        gui.alert(message, title)
    else:
        print(message)


def read_config(config_path: Path) -> Path | None:
    """读取固定路径"""
    try:
        raw = config_path.read_bytes()
    except OSError:
        return None
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            text = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if text:
            return Path(text)
    return None


def save_config(config_path: Path, folder: Path) -> None:
    """写入固定路径，若配置目录不存在时自动创建"""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(str(folder), encoding='utf-8')
    except OSError as err:
        print(f'固定路径保存失败（不影响本次解压）：{err}', file=sys.stderr)


def validate_dir(raw: str | None, gui) -> Path | None:
    if raw is None:
        return None
    text = raw.strip().strip('"')
    if not text:
        notify('路径不能为空。', '路径无效', gui)
        return None
    folder = Path(text).expanduser()
    if not folder.exists():
        notify(f'路径不存在：\n{folder}', '路径无效', gui)
        return None
    if not folder.is_dir():
        notify(f'错误文件夹：\n{folder}', '路径无效', gui)
        return None
    return folder.resolve()


def pick_directory(config_path: Path, gui) -> Path | None:
    """三选项菜单，返回 None 表示用户退出"""
    while True:
        choice = ask(
            '按1从固定路径解压缩\n'
            '按2改变固定路径\n'
            '按3输入指定路径解压缩\n'
            '按取消退出\n'
            '请输入选项：',
            APP_NAME, gui,
        )
        if choice is None:
            return None
        choice = choice.strip()

        if choice == '1':
            saved = read_config(config_path)
            if saved is None:
                entered = ask('还没有固定路径，请输入（按取消返回）：', '固定路径', gui)
                folder = validate_dir(entered, gui)
                if folder is None:
                    continue
                save_config(config_path, folder)
                return folder

            folder = validate_dir(str(saved), gui)
            if folder is None:
                notify('固定路径已失效，请用选项2重新设置。', APP_NAME, gui)
                continue
            return folder

        if choice == '2':
            entered = ask('请输入新的固定路径（按取消返回）：', '固定路径', gui)
            folder = validate_dir(entered, gui)
            if folder is None:
                continue
            save_config(config_path, folder)
            notify(f'固定路径已更新为：\n{folder}', APP_NAME, gui)
            continue

        if choice == '3':
            entered = ask('请输入欲解压压缩包所在的文件夹路径（按取消返回）：', '目录', gui)
            folder = validate_dir(entered, gui)
            if folder is None:
                continue
            return folder

        notify('请输入1、2、3。', APP_NAME, gui)


def open_folder(folder: Path) -> bool:
    try:
        if IS_WINDOWS and hasattr(os, 'startfile'):
            os.startfile(str(folder))  # Windows的打开选项
            return True
        command = ['open'] if IS_MACOS else ['xdg-open']
        subprocess.Popen(command + [str(folder)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, AttributeError):
        return False


# 命令行入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='一键解压神器.py',
        description='把文件夹内的压缩包逐个解到「已解压文件/<包名>/」。',
    )
    parser.add_argument('directory', nargs='?', help='要处理的目录；省略则走交互选择')
    parser.add_argument('--output-dir', default=OUTPUT_DIR,
                        help=f'解压输出目录名，默认{OUTPUT_DIR}')
    parser.add_argument('--recursive', action='store_true', help='递归处理子目录')
    parser.add_argument('--overwrite', action='store_true',
                        help='目标目录已存在时合并写入（默认跳过）')
    parser.add_argument('--dry-run', action='store_true', help='只列出计划，不解压')
    parser.add_argument('--no-gui', action='store_true', help='不弹窗，纯命令行')
    parser.add_argument('--config', help=f'固定路径配置文件路径，默认脚本旁{CONFIG_NAME}')
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    gui = None if args.no_gui else require_gui()

    config_path = Path(args.config) if args.config else Path(__file__).resolve().with_name(CONFIG_NAME)

    if args.directory:
        work_dir = validate_dir(args.directory, gui)
        if work_dir is None:
            return 2
    else:
        work_dir = pick_directory(config_path, gui)
        if work_dir is None:
            print('已退出程序')


    out_dir = (work_dir / args.output_dir).resolve()
    archives = collect_archives(work_dir, out_dir, args.recursive)

    if not archives:
        message = f'在{work_dir}里没找到压缩包。\n支持的格式：{"、".join(SUFFIXES)}'
        notify(message, APP_NAME, gui)
        return 1

    summary = Summary()
    for path, suffix in archives:
        display = path.relative_to(work_dir) if work_dir in path.parents else path.name
        print(f'正在解压{display}……', flush=True)
        result = process_one(path, suffix, out_dir, args.overwrite, args.dry_run)
        summary.add(result)
        if result.status == 'failed':
            print(f'失败：{result.detail}', flush=True)
        elif result.status == 'skipped':
            print(f'跳过：{result.detail}', flush=True)

    report = describe(summary)
    failures = [item for item in summary.results if item.status == 'failed']
    if failures:
        lines = [f'·{item.source.name}：{item.detail}' for item in failures[:8]]
        if len(failures) > 8:
            lines.append(f'其余{len(failures) - 8}个失败项见日志{Path(LOG_NAME).resolve().parents}')
        report += '\n\n失败明细：\n' + '\n'.join(lines)

    if args.dry_run:
        notify(f'预览模式，未改动任何文件。\n{report}', APP_NAME, gui)
        return 0

    log_path = write_log(work_dir, summary)
    if log_path:
        report += f'\n\n详细日志：{log_path}'

    notify(f'处理完成：{report}\n\n输出目录：{out_dir}', APP_NAME, gui)

    if summary.count('ok') and gui:
        answer = gui.confirm(f'是否立即打开解压后的文件夹？\n{out_dir}', APP_NAME,
                             buttons=['打开文件夹', '不用了'])
        if answer == '打开文件夹' and not open_folder(out_dir):
            notify('打开文件夹失败，请手动前往。', APP_NAME, gui)
    elif summary.count('ok'):
        print(f'解压结果在：{out_dir}')

    return 0 if not failures else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已取消操作')
        sys.exit(130)
    except TypeError:
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
