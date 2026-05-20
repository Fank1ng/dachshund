# Codex Proxy Control 用户手册

这份手册给第一次使用的新用户看。按顺序操作即可。

`Codex Proxy Control` 本地 App 是主要管理入口。浏览器里的 Web 页面只用来查看状态。

macOS 使用 `Codex Proxy Control.app`，Windows 11 使用
`CodexProxyControlSetup-0.5.0-win-x64.exe` 安装控制端。

## Mac 首次运行

### 1. 安装 App

打开下载的 DMG，把 `Codex Proxy Control.app` 拖到 Applications。

普通/本地签名版本没有 Apple 公证，新 Mac 首次打开时可能会触发 macOS 安全拦截。

### 2. 打开 App

找到 `Codex Proxy Control.app`。

优先双击打开。如果 macOS 提示“无法验证开发者”或“不明开发者”，按下面方式打开：

1. 右键点击 `Codex Proxy Control.app`
2. 选择“打开”
3. 在弹窗里再次点击“打开”

如果仍然打不开：

1. 打开“系统设置”
2. 进入“隐私与安全性”
3. 找到被拦截的 `Codex Proxy Control`
4. 点击“仍要打开”

这是 macOS 的安全检查。当前 App 是本地签名版本，新 Mac 首次打开时可能会被拦截。

### 3. 启动代理

App 打开后，点击顶部的“启动/修复”。

它会完成三件事：

- 准备运行目录：`~/Library/Application Support/codexproxyapi`
- 安装用户级后台服务：`~/Library/LaunchAgents/com.fank1ng.codexproxyapi.plist`
- 配置 Codex 使用本地代理

通常不需要管理员密码。

如果总览里提示“未找到 Codex CLI”，请先安装 Codex App，或确认 `codex` 命令已经在 PATH 中。登录账号和“打开 Codex”都依赖它。

### 4. 添加第一个账号

如果这台 Mac 上已经登录过 Codex，点击“导入当前账号”。

如果要添加新的 OpenAI 账号，点击“登录”或“打开登录页”，输入账号名称，然后在浏览器完成登录。

登录完成后，回到 App，点击“扫描”。

### 5. 启用代理

进入左侧“配置”，点击“启用代理”。

看到“Codex 模式”为“代理模式”后，说明 Codex 会走账号池代理。

### 6. 打开 Codex

点击顶部“打开 Codex”。

之后正常使用 Codex 即可。代理会自动选择可用账号。

## 日常使用

以后使用时，一般只需要：

1. 打开 `Codex Proxy Control`
2. 确认“代理状态”为“在线”
3. 点击“打开 Codex”

如果代理离线，点击“启动/修复”。

如果新增了账号，登录完成后点击“扫描”。

## Windows 11 首次运行

### 1. 下载安装包

从 GitHub Releases 下载 Windows 安装包：

```text
CodexProxyControlSetup-0.5.0-win-x64.exe
```

安装包默认安装到：

```text
%LOCALAPPDATA%\Programs\Codex Proxy Control
```

运行目录、账号和日志保存到：

```text
%LOCALAPPDATA%\codexproxyapi
```

### 2. 处理 Windows 安全提示

当前 Windows 安装包是本地构建版本，默认没有可信代码签名。Windows 11
可能会弹出 Microsoft Defender SmartScreen 或 Smart App Control 提示。

如果看到“Windows 已保护你的电脑”，点击“更多信息”，再点击“仍要运行”。

如果文件是从浏览器下载的，可以在 PowerShell 中解除下载标记：

```powershell
Unblock-File .\CodexProxyControlSetup-0.5.0-win-x64.exe
```

如果 Smart App Control 直接阻止运行，Windows 通常不会提供单次放行按钮。
这种情况下需要关闭 Smart App Control、使用源码方式运行，或使用可信证书重新签名安装包。

### 3. 启动代理

打开 `Codex Proxy Control`，点击 `Start / Repair`。

它会完成：

- 同步运行文件到 `%LOCALAPPDATA%\codexproxyapi`
- 创建当前用户计划任务 `CodexProxyApi`
- 启动后台 supervisor 和代理
- 配置 Codex 使用本地代理

看到 `Status` 中 `running: true`、`proxy_process_running: true`，说明代理已经启动。

### 4. 添加账号

在 Windows 控制端点击 `Add Account`，输入账号名称。

App 会打开一个 PowerShell 登录窗口，并执行类似命令：

```powershell
$env:CODEX_HOME='...\accounts\name'; & 'codex' login
```

随后 Codex CLI 会打开浏览器登录页。请在浏览器中完成 OpenAI/Codex 登录。

登录完成后回到 `Codex Proxy Control`，点击 `Scan Accounts`。账号出现在列表中后，
即可参与代理轮换。

如果这台 Windows 机器上已经有当前 Codex 登录态，可以点击 `Import Current`
把当前账号导入账号池。

### 5. 启用 Codex 代理

点击 `Enable Proxy`。

它会修改：

```text
C:\Users\<你的用户名>\.codex\config.toml
```

之后 Codex 会走本地代理：

```text
http://127.0.0.1:8800
```

如果需要恢复 Codex 直连官方服务，点击 `Disable Proxy`。

### 6. 常用按钮

| 按钮 | 作用 |
|------|------|
| Start / Repair | 安装或修复用户级计划任务，并启动代理 |
| Stop | 停止后台 supervisor 和代理 |
| Restart | 重启后台 supervisor 和代理 |
| Open Web UI | 打开状态诊断页 `http://127.0.0.1:8800/app` |
| Open Log | 打开 `%LOCALAPPDATA%\codexproxyapi\proxy.log` |
| Enable Proxy | 配置 Codex 使用本地代理 |
| Disable Proxy | 恢复 Codex 直连 |
| Status | 查看当前服务、进程和账号池状态 |
| Add Account | 打开可见 PowerShell 登录窗口，并弹出网页登录页 |
| Import Current | 导入当前 Codex 登录账号 |
| Delete Selected | 删除选中的账号 |
| Enable / Disable | 启用或禁用选中的账号 |
| Refresh Token | 手动刷新选中账号的 OAuth token |

## 新 Mac 常见拦截

### 提示“无法验证开发者”

原因：当前 App 是本地/ad-hoc 签名版本，不是 Apple notarized 版本。

处理：

- 右键 `Codex Proxy Control.app`，选择“打开”
- 或进入“系统设置” → “隐私与安全性” → “仍要打开”

### App 打开了，但代理没有运行

点击“启动/修复”。

代理使用用户级 LaunchAgent，安装在：

```text
~/Library/LaunchAgents/com.fank1ng.codexproxyapi.plist
```

它不需要写入系统级目录，通常不需要管理员权限。

如果仍失败，点击“打开日志”查看原因。

### `~/.codex/config.toml` 写入失败

“启用代理”会修改 Codex 配置文件：

```text
~/.codex/config.toml
```

如果写入失败，请检查：

- 文件或目录是否只读
- 是否有其他程序正在占用该文件
- 当前用户是否有 `~/.codex` 目录的写入权限

App 会尽量为修改前的配置创建备份。

### 企业电脑或安全软件拦截

部分公司电脑会限制：

- 用户级 LaunchAgent
- 本地端口 `127.0.0.1:8800`
- 未公证 App
- 后台 Python 进程

如果“启动/修复”反复失败，请打开日志，把错误内容发给维护者。

## 终端兜底命令

这些命令只用于打不开 App 或排查问题。正常使用不需要执行。

清除 macOS 隔离属性：

```bash
xattr -cr "/path/to/Codex Proxy Control.app"
```

查看代理日志：

```bash
open "$HOME/Library/Application Support/codexproxyapi/proxy.log"
```

查看运行目录：

```bash
open "$HOME/Library/Application Support/codexproxyapi"
```

## 按钮作用

### 顶部按钮

| 按钮 | 作用 |
|------|------|
| 刷新 | 重新读取代理、账号和配置状态。 |
| 启动/修复 | 安装或修复后台代理服务，并尝试启动代理。代理离线时先点它。 |
| 打开 Web | 打开浏览器状态页。只用于查看状态和最近请求。 |
| 打开 Codex | 打开 Codex，并确保代理服务已启动。 |

### 左侧导航

| 按钮 | 作用 |
|------|------|
| 总览 | 查看代理状态、可用账号、账号列表和当前账号详情。 |
| 配置 | 切换账号选择策略，启用或关闭 Codex 代理。 |
| 日志 | 查看最近请求、错误和诊断入口。 |

### 总览里的账号按钮

| 按钮 | 作用 |
|------|------|
| 额度 | 立即刷新账号额度。 |
| 扫描 | 重新读取账号目录。新增账号或登录完成后点击。 |
| 登录 | 为新账号打开登录页。登录完成后点击“扫描”。 |
| 导入 | 把当前 `~/.codex/auth.json` 保存为账号池账号。适合导入当前已登录账号。 |

### 账号检查器按钮

先在账号列表里选中一个账号，再使用这些按钮。

| 按钮 | 作用 |
|------|------|
| 刷新令牌 | 手动刷新该账号的登录令牌。 |
| 启用 | 让该账号参与账号池轮换。 |
| 禁用 | 暂停使用该账号，但不删除账号文件。 |
| 解除冷却 | 清除该账号的限流冷却状态。 |
| 解除异常 | 清除该账号的认证异常标记。 |
| 删除 / 删除账号 | 将账号移到回收目录，不直接抹除。 |

### 账号操作按钮

| 按钮 | 作用 |
|------|------|
| 复制登录命令 | 生成新账号登录命令，并复制到剪贴板。适合手动在终端登录。 |
| 打开登录页 | 自动启动登录流程，并打开 OpenAI 登录页。 |
| 导入当前账号 | 导入当前 Codex 已登录账号。 |

### 配置按钮

| 按钮 | 作用 |
|------|------|
| 轮询 | 按顺序轮换账号。 |
| 额度优先 | 优先使用剩余额度较多的账号。 |
| 启用代理 | 修改 Codex 配置，让 Codex 走本地代理。 |
| Codex 直连 | 关闭 Codex 代理配置，让 Codex 直接连接官方服务。 |
| 应用更新 | 同步 App 内置运行资源，并重启代理。正在进行的 Codex 请求可能中断。 |
| 路径与依赖 | 显示运行目录、资源目录、Python 路径等诊断信息。 |

### 日志和诊断按钮

| 按钮 | 作用 |
|------|------|
| 清空 | 清空 App 里显示的最近请求记录。 |
| 刷新 | 重新读取日志页状态。 |
| 路径 | 显示路径与依赖信息。 |
| 打开日志 | 打开代理日志文件。 |
| 打开结果文件 | 打开最近一次操作结果文件。 |
| 查看路径与依赖 | 显示运行路径和依赖信息。 |

### Web 状态页按钮

Web 状态页地址通常是：

```text
http://127.0.0.1:8800/app
```

| 按钮 | 作用 |
|------|------|
| 刷新 | 立即刷新账号额度和状态。 |

Web 页面只做状态诊断。账号管理、代理开关和修复操作请使用本地 App。

## 账号和数据位置

账号凭证保存在运行目录下：

```text
~/Library/Application Support/codexproxyapi/accounts/
```

每个账号通常包含：

```text
auth.json
account.json
quota.json
```

`auth.json` 是登录凭证。不要发给别人，不要上传到公开仓库。

## 状态说明

| 状态 | 含义 |
|------|------|
| 可用 | 账号可以参与代理请求。 |
| 已禁用 | 账号被手动停用。 |
| 冷却中 | 账号触发限流，暂时不使用。 |
| 缺令牌 | 账号没有可用登录凭证。 |
| 认证异常 | 登录凭证失效或刷新失败。 |

## 遇到问题先看这里

| 问题 | 处理 |
|------|------|
| App 打不开 | 右键打开，或到“系统设置” → “隐私与安全性”允许打开。 |
| 代理离线 | 点击“启动/修复”。 |
| 新账号没出现 | 登录完成后点击“扫描”。 |
| Codex 没走代理 | 进入“配置”，点击“启用代理”。 |
| 某个账号不用了 | 选中账号，点击“禁用”。 |
| 所有账号都限流 | 等待额度恢复，或添加新账号。 |
| 仍然失败 | 点击“打开日志”，查看错误内容。 |

## 构建 macOS DMG

维护者需要打包时运行：

```bash
./platforms/mac/build_dmg.command
```

DMG 会输出到：

```text
dist/Codex-Proxy-Control-<version>-mac.dmg
```

当前包使用本地/ad-hoc 签名，未 notarize。首次打开时，用户可能需要右键 App 并选择“打开”。构建脚本会拒绝把 `auth.json` 或 `accounts/` 账号目录打进 App 包。
