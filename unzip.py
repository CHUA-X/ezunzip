#!/usr/bin/python3
# unzip.py ——自动解压缩指定文件夹窗口内所有压缩包

from __future__ import annotations  # 让Python 3.8和3.9能兼容相关类型注解语法

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

# 常见压缩包格式
SUFFIX = ('.zip', '.rar', '.7z', 
          '.tar', '.tar.gz', '.tgz', 
          '.tar.bz2', '.tbz2','.tar.xz', 
          '.txz', '.cab')

def mainCtrl():
    """选择要操作的文件夹窗口路径
    
    :return: None
    """
    while 1:
        op = pymsgbox.prompt('按1从固定路径解压缩\n按2改变固定路径\n按3输入指定路径解压缩\n按取消退出\n请输入选项：',
                                '一键解压小程序')
        if op == '1':
            if not Path('config.conf').is_file():
                folderPath = pymsgbox.prompt('请输入固定路径（按取消返回）：', '一键解压小程序')
                if folderPath is None:
                    continue
                Path('config.conf').write_text(folderPath, encoding='utf-8')
            folderPath = Path('config.conf').read_text(encoding='utf8').strip()
            os.chdir(folderPath)
            break
        elif op == '2':
            folderPath = pymsgbox.prompt('请输入新的固定路径（按取消返回）：', '一键解压小程序')
            if folderPath is None:
                continue
            Path('config.conf').write_text(folderPath, encoding='UTF-8')
            continue
        elif op == '3':
            folderPath = pymsgbox.prompt('请输入欲解压压缩包所在目录绝对路径（按取消返回）：', '一键解压小程序')
            if folderPath is None:
                continue
            os.chdir(folderPath)
            break
        elif op is None:
            sys.exit()


def _extractByRAR(file, finalPath, **kwargs):
    """使用rarfile解压缩文件的机理
    
    :param file: 压缩包文件路径
    :param finalPath: 解压后文件的存放路径
    :return: None
    """
    import rarfile
    with rarfile.RarFile(file, 'r') as rarObj:
        # 将解压后的文件存放到已解压文件文件夹中
        rarObj.extractall(finalPath)


def _extractBy7z(file, finalPath, **kwargs):
    """使用py7zr解压缩文件的机理
    
    :param file: 压缩包文件路径
    :param finalPath: 解压后文件的存放路径
    :return: None
    """
    import py7zr
    with py7zr.SevenZipFile(file, mode='r') as seven_zObj:
        # 将解压后的文件存放到已解压文件文件夹中
        seven_zObj.extractall(finalPath)


def _extractByCAB(file, finalPath, **kwargs):
    """使用cabfile解压缩文件的机理
    
    :param file: 压缩包文件路径
    :param finalPath: 解压后文件的存放路径
    :return: None
    """
    import cabfile
    with cabfile.CabFile(file, 'r') as cabObj:
        # 将解压后的文件存放到已解压文件文件夹中
        cabObj.extractall(finalPath)

def _initializeReg():
    """注册shutil内没有的格式以便使用"""
    shutil.register_unpack_format('rar', ['.rar'], _extractByRAR, description='用于解压缩RAR格式压缩包用')
    shutil.register_unpack_format('7z', ['.7z'], _extractBy7z, description='用于解压缩7z格式压缩包用')
    shutil.register_unpack_format('cab', ['.cab'], _extractByCAB, description='用于解压缩CAB格式压缩包用')

def _catSuffix(path: Path) -> str | None:
    """返回命中的压缩包后缀（小写），不是压缩包则返回 None。

    :param path: 文件路径
    :return: 压缩包后缀（小写）或 None
    :rtype: str | None
    """
    name = path.name.lower()
    mo = [s for s in SUFFIX if name.endswith(s) and len(name) > len(s)]
    return max(mo, key=len) if mo else None

def _getName(path: Path, suffix: str) -> str:
    """从文件名去掉压缩包后缀，得到解压目标目录名。

    :param path: 压缩包文件路径
    :param suffix: 压缩包后缀
    :return: 解压目标目录名
    :rtype: str
    """
    stripped = path.name[: -len(suffix)]
    if not stripped or stripped in {'.', '..'} or stripped.strip('.') == '':
        return f'来自“{path.name}”的解压文件'
    return stripped 

if __name__ == '__main__':
    try:
        import pymsgbox

    except (ModuleNotFoundError, ImportError):
        # 若未安装相关库，则提示用户手动安装
        print('缺失pymsgbox库，请手动安装')
        sys.exit(1)

    # 执行选择文件夹路径
    mainCtrl()
    # 在文件夹下创建一个名为已解压文件的新文件夹
    os.makedirs('已解压文件', exist_ok=True)

    _initializeReg()
    basicDir = (Path.cwd() / '已解压文件').resolve()
    for fileObj in Path('.').iterdir():
        """遍历文件夹中的文件并检查"""
        # 分离文件夹、符号链接（即软链接）和非压缩包文件，避免干扰
        currentFileSuffix = _catSuffix(fileObj)
        if fileObj.is_file() and not fileObj.is_symlink() and currentFileSuffix:
            print(f'正在解压{os.path.basename(fileObj)}中······')
            # 解压压缩文件，如果有报错弹出提示框
            try:
                # 统一“.”、“..”、符号链接（即软链接）和大小写敏感的路径问题，防止发生逃逸
                finalDir = (basicDir / _getName(fileObj, currentFileSuffix)).resolve()
                if finalDir != basicDir and basicDir not in finalDir.parents:
                    pymsgbox.alert(f'解压目标路径{finalDir}不在已解压文件文件夹中，已跳过此文件的解压操作', '一键解压小程序')
                    continue
                shutil.unpack_archive(fileObj, extract_dir=finalDir)
            except Exception as err:
                pymsgbox.alert(str(err), '一键解压小程序')

    # 是否打开文件夹
    way = Path.cwd() / '已解压文件'
    flag = pymsgbox.confirm(f'所有压缩文件解压完成，解压后的文件已放入{way}。\n是否立即打开此文件夹窗口？',
                        '一键解压小程序', buttons=['是的，谢谢。', '不用了，谢谢。'])
    if flag == '是的，谢谢。':
        if platform.system() == 'Windows':  # Windows系统下打开文件夹窗口
            subprocess.Popen(['explorer', str(way)])
        elif platform.system() == 'Darwin':  # MacOS系统下打开文件夹窗口
            subprocess.Popen(['open', str(way)])
        elif platform.system() == 'Linux':  # Linux系统下打开文件夹窗口
            subprocess.Popen(['xdg-open', str(way)])
