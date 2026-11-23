"""PyInstaller 打包入口。

通过包路径导入 CLI，保证 cli.py 中的相对导入正常工作。
"""

import sys
import inspect

# Windows 控制台默认 GBK，程序输出里的 ⏳ / ⠼ 等字符会触发
# UnicodeEncodeError 并被上层误判为"转录失败"。打包运行时改为替换不可编码字符。
if getattr(sys, "frozen", False):
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

# PyInstaller 打包后 .py 源码不在磁盘上，FunASR 的注册装饰器会调用
# inspect.getsourcelines() 生成展示用元数据，此时抛 "could not get source code"。
# 该函数在 frozen 环境下返回占位值即可，不影响模型加载与转录。
if getattr(sys, "frozen", False):
    _orig_getsourcelines = inspect.getsourcelines

    def _frozen_getsourcelines(obj):
        try:
            return _orig_getsourcelines(obj)
        except (OSError, TypeError, IOError):
            return (["# source unavailable in frozen build\n"], 1)

    inspect.getsourcelines = _frozen_getsourcelines

    # FunASR 的 cif_predictor 等模块在导入时执行 @torch.jit.script。
    # 若打包环境仍拿不到源码，退化为普通 Python 函数即可（功能不变，仅少一点加速）。
    try:
        import torch

        _orig_jit_script = torch.jit.script

        def _frozen_jit_script(obj, *args, **kwargs):
            try:
                return _orig_jit_script(obj, *args, **kwargs)
            except Exception:
                return obj

        torch.jit.script = _frozen_jit_script
    except Exception:
        pass

from videocut.cli import main

if __name__ == "__main__":
    main()
