# Codex Proxy Control Windows 版

> Windows 版使用 PyInstaller 生成控制端和后台 supervisor，再用 Inno Setup
> 生成用户级安装包。根目录里的稳定 macOS 源码和打包脚本保持不动。

## 构建安装包

在 Windows 11 x64 上安装 Python 3.11/3.12、Git、Inno Setup 6 后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\platforms\windows\build_windows.ps1 -Version 0.6.7
```

脚本会生成：

- `dist\windows\Codex Proxy Control.exe`
- `dist\windows\CodexProxyService.exe`
- `dist\CodexProxyControlSetup-0.6.7-win-x64.exe`（已安装 Inno Setup 时）

如果只想生成便携文件：

```powershell
.\platforms\windows\build_windows.ps1 -Version 0.6.7 -SkipInstaller
```

## 安装与运行

已发布的 Windows 安装包在 GitHub Release:

```text
https://github.com/Fank1ng/codexproxyapi/releases/tag/v0.6.7
```

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

## Windows 11 安全拦截

本地用 PyInstaller/Inno Setup 生成的安装包默认没有可信代码签名。Windows 11
可能会被 Microsoft Defender SmartScreen 或 Smart App Control 拦截，提示
“智能应用控制已阻止此应用”或类似警告。这是系统对未知发布者安装包的拦截，
不是代理启动代码异常。

如果是 SmartScreen 的“Windows 已保护你的电脑”提示，可以点击“更多信息”
再选择“仍要运行”。如果文件是从浏览器或聊天工具下载到本机，也可以先解除
下载标记：

```powershell
Unblock-File .\dist\CodexProxyControlSetup-0.6.7-win-x64.exe
```

如果是 Smart App Control 直接阻止，Windows 通常不会提供单次放行按钮。
可选处理方式：

- 使用源码方式运行，跳过未签名 exe 安装包。
- 在 Windows 安全中心关闭 Smart App Control 后再安装。注意关闭后通常不能
  直接重新开启，可能需要重置或重装 Windows。
- 为 `Codex Proxy Control.exe`、`CodexProxyService.exe` 和安装包使用可信
  代码签名证书签名，这是长期分发给其他机器时推荐的方式。

## 兜底脚本

源码目录下可直接运行：

```powershell
.\platforms\windows\setup_proxy.ps1
.\platforms\windows\start_codex.ps1
```

登录命令会使用 PowerShell 格式：

```powershell
$env:CODEX_HOME='...\accounts\name'; & 'codex' login
```
