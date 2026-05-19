# Codex Proxy Control Windows 版

> 当前文档和 `windows/` 下的脚本是 Windows 版的隔离起点，来源于旧实验目录。
> 现阶段没有移动根目录里的稳定 macOS 源码；正式 Windows 功能开发时，需要继续把
> Windows 后台任务、控制端动作和安装流程适配到当前主线源码。

## 构建安装包

在 Windows 10/11 x64 上执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows\build_windows.ps1
```

脚本会生成：

- `dist\windows\Codex Proxy Control.exe`
- `dist\windows\CodexProxyService.exe`
- `dist\CodexProxyControlSetup-0.4.3.exe`（已安装 Inno Setup 时）

如果只想生成便携文件：

```powershell
.\windows\build_windows.ps1 -SkipInstaller
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
