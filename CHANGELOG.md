# Changelog

## v0.6.4 - 2026-06-14

- Added a first-success guide in the macOS app that walks through backend startup, Codex detection, account readiness, proxy enablement, opening Codex, and confirming model traffic is pooled.
- Simplified user-facing configuration to a single “额度优先” strategy while keeping round-robin fallback and legacy config compatibility internally.
- Hid advanced stream, heartbeat, timeout, quota-weight, and Web status controls from the normal macOS app surface.
- Made the macOS app's automatic refresh sync status quietly without disabling controls, changing sections, or rebuilding the active view.

## v0.6.3 - 2026-06-14

- Refined the macOS control app sidebar for light appearance with native-feeling dynamic colors.
- Aligned the sidebar panel edge spacing, hid the outer content scrollbar, and removed bottom page status text.
- Kept the fixed 600x460 window, 118px sidebar, and 450px overview card layout.

## v0.6.2 - 2026-06-12

- Restyled the macOS control app with a hidden titlebar title, no top divider, and closed rounded sidebar panels.
- Packaged the macOS release as XiaoLaChang 0.6.2.

## v0.6.0 - 2026-06-10

- Hardened macOS update sync with staging validation, rollback, and update locking.
- Updated macOS app branding, runtime paths, and usage tracking for the XiaoLaChang release.
- Fully retire the legacy LaunchAgent on install (bootout, disable, remove plist, and move the old runtime aside) so the old service stops fighting for port 8800.
- Run the repair/open actions from the pristine app bundle so a stale runtime can self-heal instead of only apply-update working.

## v0.5.4 - 2026-06-10

- Fixed macOS update repair detection for LaunchAgent source, app bundle, Python, and Python path mismatches.
- Made macOS apply-update wait for the newly packaged proxy version before reporting success.
- Changed most-available quota weighting to 5h/7d = 5:5 for new default configs.

## v0.5.3 - 2026-06-09

- Fixed Codex CLI compact requests so `/v1/responses/compact` no longer requires a `response.completed` event before returning a successful compact response.
- Preserved completion-marker enforcement for normal Codex response streams while avoiding false `stream_interrupted` cooldowns for compact responses.
- Switched Codex response streaming to realtime by default, with SSE keepalives, bootstrap retry limits, disabled proxy-initiated WebSocket heartbeat, and session affinity for long Codex tasks.
- Synced the macOS packaged core with the shared proxy fix.

## v0.5.2 - 2026-06-07

- Routed Codex `/v1/responses` traffic through the ChatGPT Codex backend while preserving the OpenAI Responses wire API configuration.
- Added WebSocket-aware proxying, hybrid Codex stream buffering, retry cooldowns, and interruption diagnostics for streamed model responses.
- Exposed Codex stream mode and transport details in recent request logs and the web dashboard.
- Updated Codex CLI proxy config generation to enable WebSocket support and retain legacy Codex backend detection.
- Expanded core tests for routing, streaming, WebSocket relay behavior, cooldown handling, and stream configuration validation.

## v0.5.1 - 2026-06-01

- Added shared Codex CLI discovery for Windows and macOS control flows.
- Improved Windows Codex CLI lookup for local app installs, PATH entries, and registry hints.
- Added clear `CODEX_CLI_PATH` guidance when the Codex CLI cannot be found.
- Standardized UTF-8 file and subprocess handling for Windows release builds.
- Included `codex_cli.py` in the Windows runtime packaging list.

## v0.5.0 - 2026-05-20

- Added the first Windows 11 installer path using PyInstaller and Inno Setup.
- Added a Windows Scheduled Task service helper for user-level background startup.
- Added a minimal Windows control app for starting, stopping, restarting, opening the Web UI, opening logs, and toggling Codex proxy mode.
- Updated Windows PowerShell helper scripts to use the Windows service CLI instead of macOS LaunchAgent actions.
- Added packaging guards to reject credentials, `.docx` files, macOS app bundles, and copied runtime dependency trees.
- Updated Windows documentation for the `0.5.0` installer build flow.
- Uploaded the Windows installer and existing `Codex-Proxy-Control-0.4.3-mac.dmg` to the `v0.5.0` GitHub release.
- Reorganized source into `src/core`, `platforms/mac`, and `platforms/windows`.
