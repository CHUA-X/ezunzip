#!/usr/bin/python3
# Error.py ——程序异常定义


class ArchiveError(Exception):
    """解压过程中的可预期错误"""


class UnsafeArchive(ArchiveError):
    """压缩包包含越界路径或不允许写出的特殊文件"""


class MissingDLL(ArchiveError):
    """缺少或无法加载所需DLL"""
