#!/usr/bin/python3
# toolbox.py ——压缩包命名、内容识别和单个文件处理等工具函数

from pathlib import Path

from Error import ArchiveError
from uncompressed import extract_archive, is_supported_archive


# 仅用于从文件名去掉后缀；不用于判断是否为归档。
DEFAULT_SUFFIXES = (
    ".tar.bz2", ".tar.lzma", ".tar.lz", ".tar.lzo", ".tar.lz4",
    ".tar.zst", ".tar.gz", ".tar.xz", ".tar.z",
    ".cpio.bz2", ".cpio.gz", ".cpio.xz",
    ".tgz", ".tbz2", ".txz", ".tlz", ".taz", ".tzst",
    ".zip", ".jar", ".war", ".ear", ".apk", ".ipa", ".cbz", ".whl",
    ".rar", ".7z", ".cab", ".cpio", ".tar",
    ".iso9660", ".iso", ".lha", ".lzh", ".mtree",
    ".xar", ".pkg", ".deb", ".ar", ".a",
)


class Tools:
    def __init__(self, suffixes=None):
        self.suffixes = tuple(
            suffix.lower()
            for suffix in (suffixes or DEFAULT_SUFFIXES)
        )

    def catSuffix(self, path):
        """返回已知后缀，用于目标目录命名"""
        name = Path(path).name.lower()
        matches = [
            suffix
            for suffix in self.suffixes
            if name.endswith(suffix) and len(name) > len(suffix)
        ]
        return max(matches, key=len) if matches else None

    @staticmethod
    def getName(path, suffix=None):
        """有已知后缀时去掉后缀，否则使用完整文件名。"""
        path = Path(path)

        if suffix:
            name = path.name[:-len(suffix)]
        else:
            name = path.name

        return name or f"来自“{path.name}”的解压文件"

    @staticmethod
    def isArchive(path):
        """按文件内容探测是否为 libarchive 支持的归档。"""
        return is_supported_archive(path)


class Exec:
    @staticmethod
    def mainChk(basicDir, fileObj, suffix=None, overwrite=False):
        """处理单个归档，返回 (状态, 说明)。"""
        basic_dir = Path(basicDir).resolve()
        file_obj = Path(fileObj)
        target = basic_dir / Tools.getName(file_obj, suffix)

        try:
            if target.exists():
                resolved_target = target.resolve()
                if (
                    resolved_target != basic_dir
                    and basic_dir not in resolved_target.parents
                ):
                    return "failed", f"目标目录越界：{target}"

            has_content = False
            if target.is_dir():
                try:
                    has_content = any(target.iterdir())
                except OSError:
                    pass

            if has_content and not overwrite:
                return "skipped", f"目标已存在：{target.name}"

            target.mkdir(parents=True, exist_ok=True)
            count = extract_archive(file_obj, target)
            return "ok", f"{count} 个文件"

        except Exception as err:
            try:
                if target.is_dir() and not any(target.iterdir()):
                    target.rmdir()
            except OSError:
                pass

            if isinstance(err, ArchiveError):
                return "failed", str(err)

            return "failed", f"{type(err).__name__}: {err}"
