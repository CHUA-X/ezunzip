#!/usr/bin/python3
# 同夹压缩速解精灵2——自动解压缩指定文件夹窗口内所有压缩包，可以解压
# ZIP、RAR、7z、TAR、tar.gz（tgz）、tar.bz2（tbz2）、tar.xz（txz）、cab等格式

# 本程序包含：
# unzip.py ——主程序
# Error.py ——异常发生模块
# toolbox.py ——解压缩所需工具模块
# uncompressed.py ——解压缩模块
# ui.py ——界面模块

# 依赖的模块：
# pymsgbox ——> 界面框的组成

# 依赖的外部文件：
# achieve.dll（由libachieve C语言库编译而来）

from __future__ import annotations

import sys
import logging
import platform
import subprocess
from pathlib import Path

try:
    import pymsgbox
except ImportError:
    print("缺少 pymsgbox，请先安装：python -m pip install pymsgbox")
    sys.exit(1)

from Error import ArchiveError
from toolbox import Exec, Tools
from ui import mainGUI
from uncompressed import _importDLL, is_supported_archive

logging.disable(logging.CRITICAL) # 最终成品记得去掉注释
    
def open(folder):
    """控制不同平台打开输出目录"""
    try:
        system = platform.system()

        if system == "Windows":
            subprocess.Popen(["explorer", str(folder)])
        elif system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        elif system == "Linux":
            subprocess.Popen(["xdg-open", str(folder)])
        else:
            return False

        return True

    except OSError as err:
        logging.error(f"打开输出目录失败：{err}")
        return False


def main():
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y年%m月%d日 %H:%M:%S",
            handlers=[
                logging.FileHandler(
                    Path(base_dir) / "日志.log",
                    encoding="utf-8",
                    delay=True,
                ),
                logging.StreamHandler(sys.stdout),
            ],
        )

    work_dir = mainGUI()
    if work_dir is None:
        print("已退出。")
        return 0

    work_dir = Path(work_dir).resolve()
    output_dir = (work_dir / "已解压文件").resolve()

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        logging.exception("创建输出目录失败")
        pymsgbox.alert(
            f"创建输出目录失败：\n{err}",
            "一键解压小程序",
        )
        return 1

    # 启动时只加载一次 DLL，避免每个文件都重复报告依赖错误。
    try:
        _load_libarchive()
    except ArchiveError as err:
        logging.exception("加载 libarchive 失败")
        pymsgbox.alert(str(err), "一键解压小程序")
        return 1

    tools = Tools()
    candidates = []
    recognition_errors = []

    for path in sorted(work_dir.iterdir(), key=lambda item: item.name.lower()):
        try:
            if path == output_dir or output_dir in path.parents:
                continue

            if not path.is_file() or path.is_symlink():
                continue

            # 用后缀决定文件名
            suffix = tools.catSuffix(path)

            if is_supported_archive(path):
                candidates.append((path, suffix))

        except (OSError, ArchiveError) as err:
            recognition_errors.append((path, str(err)))
        except Exception as err:
            recognition_errors.append(
                (path, f"{type(err).__name__}: {err}")
            )

    okPkg = 0
    passedPkg = 0
    failedPkg = 0
    failDetails = []

    for path, suffix in candidates:
        print(f"正在解压{path.name}中……", flush=True)

        status, detail = Exec.mainChk(output_dir, path, suffix)

        if status == "ok":
            ok += 1
            print(f"成功：{detail}", flush=True)
        elif status == "skipped":
            skipped += 1
            print(f"跳过：{detail}", flush=True)
        else:
            failed += 1
            failDetails.append((path, detail))
            logging.error(f"解压{path}失败：{detail}")
            print(f"  失败：{detail}", flush=True)

    for path, detail in recognition_errors:
        failed += 1
        failDetails.append((path, f"识别失败：{detail}"))
        logging.error(f"识别{path}失败：{detail}")

    report = (
        f"处理完成：成功{okPkg}个，"
        f"跳过{passedPkg}个，"
        f"失败{failedPkg}个。"
    )

    if failDetails:
        report += "\n\n失败明细："
        for path, detail in failDetails[:8]:
            report += f"\n·{path.name}：{detail}"
        if len(failDetails) > 8:
            report += (
                f"\n· 其余{len(failDetails) - 8}项详见日志.log"
            )

    report += f"\n\n输出目录：\n{output_dir}"
    pymsgbox.alert(report, "一键解压小程序")

    if ok:
        answer = pymsgbox.confirm(
            f"是否立即打开解压后的文件夹？\n{output_dir}",
            "一键解压小程序",
            buttons=["打开文件夹", "不用了"],
        )
        if answer == "打开文件夹" and not open(output_dir):
            pymsgbox.alert(
                "打开文件夹失败！请手动前往输出目录",
                "一键解压小程序",
            )

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n操作取消。")
        sys.exit(130)
    except Exception as err:
        logging.exception("有错误")
        print(f"程序发生错误：{err}")
        sys.exit(1)
