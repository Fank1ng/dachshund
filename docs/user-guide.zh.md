# Dachshund 用户指南

## 安装

下载 `dachshund-<version>-mac.dmg`，把 `dachshund.app` 拖到
Applications。

如果 macOS 提示无法验证开发者，右键点击 `dachshund.app`，选择“打开”。

## 启动代理

打开 Dachshund，点击“启动/修复”。它会准备：

- 运行目录：`~/Library/Application Support/dachshund`
- 后台服务：`~/Library/LaunchAgents/com.fank1ng.dachshund.plist`
- 本地 API：`http://127.0.0.1:18800`

## 添加账号

在“账号”页输入账号名称，然后选择：

- “开始登录”：打开 Codex 登录流程
- “导入当前 Codex 账号”：导入本机已有 Codex 登录
- “扫描”：刷新账号列表

账号令牌保存在本机运行目录，不会写入仓库。

## 启用 Codex 代理

进入“配置”，点击“启用 Codex 代理”。Dachshund 会写入
`~/.codex/config.toml`，让 Codex 使用本地代理。

需要恢复直连时，点击“Codex 直连”。

## 日常使用

1. 打开 `dachshund.app`
2. 确认状态为“代理在线”
3. 打开 Codex

日志路径：

```sh
open "$HOME/Library/Application Support/dachshund/proxy.log"
```

账号目录：

```sh
open "$HOME/Library/Application Support/dachshund/accounts"
```
