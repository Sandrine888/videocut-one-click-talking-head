# Windows 安装包构建指南

## 方法一：使用打包脚本（推荐）

### 前置要求

1. Windows 10/11
2. Python 3.10+ ([下载](https://www.python.org/downloads/))
3. FFmpeg ([下载](https://ffmpeg.org/download.html))

### 构建步骤

1. 在 Windows 上克隆或下载项目
2. 双击运行 `build_windows.bat`
3. 等待打包完成（约5-10分钟）
4. 安装包在 `installer/videocut.exe`

## 方法二：手动打包

```powershell
# 1. 创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. 安装依赖
pip install -e .
pip install pyinstaller

# 3. 打包
pyinstaller videocut.spec

# 4. 输出在 dist/videocut.exe
```

## 方法三：使用 Inno Setup 创建安装程序

### 安装 Inno Setup

下载: https://jrsoftware.org/isdl.php

### 创建安装脚本

使用以下 `installer.iss` 配置：

```iss
[Setup]
AppName=Videocut
AppVersion=0.1.0
DefaultDirName={autopf}\Videocut
DefaultGroupName=Videocut
OutputBaseFilename=Videocut_Setup_0.1.0
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\videocut.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Videocut"; Filename: "{app}\videocut.exe"
Name: "{group}\Uninstall Videocut"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\videocut.exe"; Parameters: "--help"; Description: "运行 Videocut"; Flags: postinstall shellexec skipifsilent
```

### 构建安装程序

1. 先运行 `build_windows.bat` 生成 exe
2. 打开 Inno Setup
3. 打开 `installer.iss`
4. 点击 Build -> Compile
5. 生成 `Videocut_Setup_0.1.0.exe`

## 分发注意事项

### 包含文件

```
Videocut/
├── videocut.exe      # 主程序
├── README.md         # 使用说明
└── ffmpeg.exe        # 需要单独下载或打包
```

### FFmpeg 处理

用户需要自行安装 FFmpeg，或者：

1. 下载 FFmpeg Windows 版本
2. 将 `ffmpeg.exe` 放在 Videocut 安装目录
3. 或添加到系统 PATH

### 首次运行

1. 运行 `videocut init` 配置
2. 首次转录会下载语音模型（约1GB）

## 常见问题

### Q: 打包后 exe 太大？

A: PyInstaller 会打包所有依赖，torch 等库较大。可以使用 UPX 压缩。

### Q: 运行时缺少 DLL？

A: 确保安装了 Visual C++ Redistributable：
https://aka.ms/vs/17/release/vc_redist.x64.exe

### Q: 杀毒软件误报？

A: PyInstaller 打包的 exe 可能触发误报，可以：
- 添加白名单
- 使用代码签名证书签名
