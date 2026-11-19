#!/usr/bin/python3
# ui.py ——图形界面选择工作目录并保存固定路径

import sys
import logging
from pathlib import Path

try:
    import pymsgbox
except ImportError:
    print("缺少 pymsgbox，请先安装：python -m pip install pymsgbox")
    sys.exit(1)


def _validate_folder(text):
    if text is None:
        return None

    text = text.strip().strip('"')
    if not text:
        pymsgbox.alert("路径不能为空！", "一键解压小程序")
        return None

    folder = Path(text).expanduser()

    if not folder.exists():
        pymsgbox.alert(f"路径不存在：\n{folder}", "一键解压小程序")
        return None

    if not folder.is_dir():
        pymsgbox.alert(f"这不是文件夹：\n{folder}", "一键解压小程序")
        return None

    return folder.resolve()


def mainGUI(): 
    """显示选择目录菜单
    返回所选目录，取消时返回None"""
    logging.info("当前工作目录：%s", Path.cwd())

    config_path = Path(__file__).resolve().parent / "config.conf"

    while True:
        op = pymsgbox.prompt(
            "按1从固定路径解压缩\n"
            "按2改变固定路径\n"
            "按3输入指定路径解压缩\n"
            "按取消退出\n"
            "请输入选项：",
            "一键解压小程序",
        )

        if op is None:
            return op

        op = op.strip()

        if op == "1":
            saved_path = None

            if config_path.is_file():
                try:
                    saved_path = config_path.read_text(
                        encoding="utf-8-sig"
                    ).strip()
                except OSError as err:
                    pymsgbox.alert(
                        f"读取固定路径失败：\n{err}",
                        "一键解压小程序",
                    )
                    continue

            if not saved_path:
                entered = pymsgbox.prompt(
                    "请输入固定路径（按取消返回）：",
                    "固定路径",
                )
                folder = _validate_folder(entered)
                if folder is None:
                    continue

                try:
                    config_path.write_text(str(folder), encoding="utf-8")
                except OSError as err:
                    pymsgbox.alert(
                        f"保存固定路径失败：\n{err}",
                        "一键解压小程序",
                    )
                    continue

                return folder

            folder = _validate_folder(saved_path)
            if folder is not None:
                return folder

            pymsgbox.alert(
                "固定路径无效，请用选项2重新设置",
                "一键解压小程序",
            )

        elif op == "2":
            entered = pymsgbox.prompt(
                "请输入新的固定路径（按取消返回）：",
                "固定路径",
            )
            if entered is None:
                continue

            folder = _validate_folder(entered)
            if folder is None:
                continue

            try:
                config_path.write_text(str(folder), encoding="utf-8")
            except OSError as err:
                pymsgbox.alert(
                    f"保存固定路径失败：\n{err}",
                    "一键解压小程序",
                )
                continue

            pymsgbox.alert(
                f"固定路径已更新为：\n{folder}",
                "一键解压小程序",
            )

        elif op == "3":
            entered = pymsgbox.prompt(
                "请输入压缩包所在文件夹路径（按取消返回）：",
                "选择目录",
            )
            folder = _validate_folder(entered)
            if folder is not None:
                return folder

        else:
            pymsgbox.alert(
                "请输入1、2或3",
                "一键解压小程序",
            )
