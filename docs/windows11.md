# Codex Proxy Control Windows 版

> Windows 版使用 PyInstaller 生成控制端和后台 supervisor，再用 Inno Setup
> 生成用户级安装包。根目录里的稳定 macOS 源码和打包脚本保持不动。

## 构建安装包

在 Windows 11 x64 上安装 Python 3.11/3.12、Git、Inno Setup 6 后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows\build_windows.ps1 -Version 0.5.0
```

脚本会生成：

- `dist\windows\Codex Proxy Control.exe`
- `dist\windows\CodexProxyService.exe`
- `dist\CodexProxyControlSetup-0.5.0-win-x64.exe`（已安装 Inno Setup 时）

如果只想生成便携文件：

```powershell
.\windows\build_windows.ps1 -Version 0.5.0 -SkipInstaller
```

## 安装与运行

安装包默认安装到：

```text
%LOCALAPPDATA%\Programs\Codex Proxy Control
```

运行目录和账号数据保存到：

```text
%LOCALAPPDATA%\codexproxyapi
```

控制 App 中点击“Start / Repair”会完成：

- 同步运行文件到 `%LOCALAPPDATA%\codexproxyapi`
- 创建当前用户计划任务 `CodexProxyApi`
- 启动后台 supervisor 和代理
- 写入 Codex 代理配置

卸载会删除计划任务并停止后台进程，但不会删除 `%LOCALAPPDATA%\codexproxyapi\accounts` 里的账号凭证。

## 兜底脚本

源码目录下可直接运行：

```powershell
.\windows\setup_proxy.ps1
.\windows\start_codex.ps1
```

登录命令会使用 PowerShell 格式：

```powershell
$env:CODEX_HOME='...\accounts\name'; & 'codex' login
```
