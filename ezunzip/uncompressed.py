#!/usr/bin/python3
# uncompressed.py ——使用libarchive的archive.dll探测并解压归档

import os
import stat
import ctypes
import shutil
from pathlib import Path

from Error import ArchiveError, MissingDLL, UnsafeArchive


_LIBARCHIVE = None
_DLL_DIRECTORY = None

_READ_BUFFER_SIZE = 1024 * 1024
_ARCHIVE_EOF = 1


def _importDLL():
    """从程序目录或 bin 子目录加载 archive.dll"""
    global _LIBARCHIVE, _DLL_DIRECTORY

    if _LIBARCHIVE is not None:
        return _LIBARCHIVE

    baseDir = Path(__file__).resolve().parent
    whereDLL = next(
        (
            candidate
            for candidate in (
                baseDir / "archive.dll",
                baseDir / "bin" / "archive.dll",
            )
            if candidate.is_file()
        ),
        None,
    )

    if whereDLL is None:
        raise MissingDLL(
            "找不到 archive.dll。请把它放在程序目录，"
            "或放在程序目录下的 bin 文件夹。"
        )

    try:
        if hasattr(os, "add_dll_directory"):
            _DLL_DIRECTORY = os.add_dll_directory(str(whereDLL.parent))
        lib = ctypes.WinDLL(str(whereDLL))
    except (OSError, AttributeError) as err:
        raise MissingDLL(f"加载archive.dll失败：{err}") from err

    lib.archive_read_new.restype = ctypes.c_void_p

    for name in (
        "archive_read_support_format_all",
        "archive_read_support_filter_all",
    ):
        func = getattr(lib, name)
        func.argtypes = [ctypes.c_void_p]
        func.restype = ctypes.c_int

    lib.archive_read_open_filename_w.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_size_t,
    ]
    lib.archive_read_open_filename_w.restype = ctypes.c_int

    lib.archive_read_next_header.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.archive_read_next_header.restype = ctypes.c_int

    lib.archive_format_name.argtypes = [ctypes.c_void_p]
    lib.archive_format_name.restype = ctypes.c_char_p

    lib.archive_entry_pathname_utf8.argtypes = [ctypes.c_void_p]
    lib.archive_entry_pathname_utf8.restype = ctypes.c_char_p

    lib.archive_entry_filetype.argtypes = [ctypes.c_void_p]
    lib.archive_entry_filetype.restype = ctypes.c_uint

    lib.archive_entry_size.argtypes = [ctypes.c_void_p]
    lib.archive_entry_size.restype = ctypes.c_int64

    lib.archive_read_data_skip.argtypes = [ctypes.c_void_p]
    lib.archive_read_data_skip.restype = ctypes.c_int

    lib.archive_read_data.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    lib.archive_read_data.restype = ctypes.c_ssize_t

    lib.archive_error_string.argtypes = [ctypes.c_void_p]
    lib.archive_error_string.restype = ctypes.c_char_p

    lib.archive_read_free.argtypes = [ctypes.c_void_p]
    lib.archive_read_free.restype = ctypes.c_int

    _LIBARCHIVE = lib
    return lib


def _error_text(lib, reader):
    raw = lib.archive_error_string(reader)
    if not raw:
        return "未知 libarchive 错误"
    return raw.decode("utf-8", errors="replace")


def _configure_reader(lib, reader):
    for func in (
        lib.archive_read_support_filter_all,
        lib.archive_read_support_format_all,
    ):
        if func(reader) != 0:
            raise ArchiveError(
                f"初始化 libarchive 失败：{_error_text(lib, reader)}"
            )


def _open_archive(src):
    """打开归档，返回 (library, reader)。"""
    lib = _importDLL()
    reader = lib.archive_read_new()

    if not reader:
        raise ArchiveError("创建 libarchive 读取器失败")

    try:
        _configure_reader(lib, reader)

        status = lib.archive_read_open_filename_w(
            reader,
            str(Path(src).resolve()),
            10240,
        )
        if status != 0:
            raise ArchiveError(f"无法打开文件：{_error_text(lib, reader)}")

        return lib, reader

    except Exception:
        lib.archive_read_free(reader)
        raise


def is_supported_archive(path):
    """按内容判断文件是否为 libarchive 支持的归档。

    空文件和 libarchive 的 raw 流不视为归档。
    """
    lib = _importDLL()
    reader = lib.archive_read_new()

    if not reader:
        raise ArchiveError("创建 libarchive 读取器失败")

    try:
        _configure_reader(lib, reader)

        status = lib.archive_read_open_filename_w(
            reader,
            str(Path(path).resolve()),
            10240,
        )
        if status != 0:
            return False

        entry = ctypes.c_void_p()
        status = lib.archive_read_next_header(reader, ctypes.byref(entry))

        if status not in (0, _ARCHIVE_EOF):
            return False

        raw_name = lib.archive_format_name(reader)
        if not raw_name:
            return False

        format_name = raw_name.decode("utf-8", errors="replace").strip().lower()
        return format_name not in ("empty file", "raw", "raw data")

    finally:
        lib.archive_read_free(reader)


def _member_name(lib, entry):
    raw = lib.archive_entry_pathname_utf8(entry)
    if raw is None:
        raise ArchiveError("压缩包内有无法读取名称的文件")
    return raw.decode("utf-8", errors="replace")


def _is_safe_member(name):
    """拒绝绝对路径、盘符路径、路径穿越及冒号路径。"""
    if not name:
        return False

    normalized = name.replace("\\", "/")

    if normalized.startswith("/"):
        return False

    if len(normalized) >= 2 and normalized[1] == ":":
        return False

    parts = [
        part
        for part in normalized.split("/")
        if part not in ("", ".")
    ]

    return ".." not in parts and not any(":" in part for part in parts)


def _safe_output_path(dest, name):
    if not _is_safe_member(name):
        raise UnsafeArchive(f"压缩包内含越界路径，已拒绝解压：{name}")

    parts = [
        part
        for part in name.replace("\\", "/").split("/")
        if part not in ("", ".")
    ]

    root = Path(dest).resolve()
    if not parts:
        return root

    output = root.joinpath(*parts)

    try:
        resolved = output.resolve()
    except OSError as err:
        raise ArchiveError(f"无法检查输出路径：{name}：{err}") from err

    if resolved != root and root not in resolved.parents:
        raise UnsafeArchive(f"压缩包路径越界，已拒绝解压：{name}")

    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeArchive(
                f"输出路径包含符号链接，已拒绝写入：{current}"
            )

    return output


def _scan_archive(src):
    """解压前检查成员路径、类型并估算所需空间。"""
    lib, reader = _open_archive(src)
    members = []
    required_size = 0

    try:
        entry = ctypes.c_void_p()

        while True:
            status = lib.archive_read_next_header(reader, ctypes.byref(entry))

            if status == _ARCHIVE_EOF:
                break

            if status != 0:
                raise ArchiveError(
                    f"读取压缩包目录失败：{_error_text(lib, reader)}"
                )

            name = _member_name(lib, entry)
            if not _is_safe_member(name):
                raise UnsafeArchive(
                    f"压缩包内含越界路径，已拒绝解压：{name}"
                )

            filetype = lib.archive_entry_filetype(entry)
            if filetype not in (stat.S_IFDIR, stat.S_IFREG):
                raise UnsafeArchive(
                    f"压缩包内含不允许解压的链接或特殊文件：{name}"
                )

            size = max(0, lib.archive_entry_size(entry))
            if filetype == stat.S_IFREG:
                required_size += size

            members.append((name.replace("\\", "/"), filetype, size))

            if lib.archive_read_data_skip(reader) != 0:
                raise ArchiveError(
                    f"读取压缩包内容失败：{_error_text(lib, reader)}"
                )

    finally:
        lib.archive_read_free(reader)

    return members, required_size


def _check_free_space(dest, needed):
    if needed <= 0:
        return

    probe = Path(dest)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent

    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return

    if needed > free:
        raise ArchiveError(
            f"目标磁盘空间不足：需要约 {needed} 字节，剩余 {free} 字节"
        )


def extract_archive(src, dest):
    """解压归档至目标目录，返回写出的普通文件数。"""
    src = Path(src)
    dest = Path(dest)

    members, required_size = _scan_archive(src)
    _check_free_space(dest, required_size)

    lib, reader = _open_archive(src)
    count = 0
    member_index = 0

    try:
        entry = ctypes.c_void_p()
        buffer = ctypes.create_string_buffer(_READ_BUFFER_SIZE)

        while True:
            status = lib.archive_read_next_header(reader, ctypes.byref(entry))

            if status == _ARCHIVE_EOF:
                break

            if status != 0:
                raise ArchiveError(
                    f"解压时读取压缩包失败：{_error_text(lib, reader)}"
                )

            name = _member_name(lib, entry).replace("\\", "/")
            filetype = lib.archive_entry_filetype(entry)

            if (
                member_index >= len(members)
                or members[member_index][0] != name
                or members[member_index][1] != filetype
            ):
                raise ArchiveError("压缩包内容在检查后发生变化，请重试")

            member_index += 1
            parts = [part for part in name.split("/") if part not in ("", ".")]

            if not parts:
                if lib.archive_read_data_skip(reader) != 0:
                    raise ArchiveError(
                        f"读取压缩包内容失败：{_error_text(lib, reader)}"
                    )
                continue

            output_path = _safe_output_path(dest, name)

            if filetype == stat.S_IFDIR:
                output_path.mkdir(parents=True, exist_ok=True)
                _safe_output_path(dest, name)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            _safe_output_path(dest, name)

            try:
                with open(output_path, "wb") as sink:
                    while True:
                        length = lib.archive_read_data(
                            reader,
                            buffer,
                            len(buffer),
                        )

                        if length == 0:
                            break

                        if length < 0:
                            raise ArchiveError(
                                f"解压 {name} 失败：{_error_text(lib, reader)}"
                            )

                        sink.write(buffer.raw[:length])

            except OSError as err:
                raise ArchiveError(
                    f"写入文件失败：{output_path}：{err}"
                ) from err

            count += 1

    finally:
        lib.archive_read_free(reader)

    if member_index != len(members):
        raise ArchiveError("压缩包内容在检查后发生变化，请重试")

    return count
