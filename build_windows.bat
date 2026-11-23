@echo off
REM Videocut Windows 打包脚本
REM 在 Windows 上运行此脚本生成 exe 安装包

echo ========================================
echo Videocut Windows 打包工具
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 创建虚拟环境
echo [1/5] 创建虚拟环境...
if not exist "venv_build" (
    python -m venv venv_build
)
call venv_build\Scripts\activate.bat

REM 安装依赖
echo [2/5] 安装依赖...
pip install -q -e .
pip install -q pyinstaller

REM 打包
echo [3/5] 打包中（可能需要几分钟）...
pyinstaller videocut.spec --noconfirm

REM 检查结果
if exist "dist\videocut.exe" (
    echo.
    echo [4/5] 打包成功！
    echo 输出文件: dist\videocut.exe

    REM 创建安装包目录
    echo [5/5] 创建安装包...
    if not exist "installer" mkdir installer
    copy dist\videocut.exe installer\
    copy README.md installer\

    echo.
    echo ========================================
    echo 打包完成！
    echo 安装包位置: installer\videocut.exe
    echo ========================================
) else (
    echo.
    echo [错误] 打包失败，请检查错误信息
)

pause
