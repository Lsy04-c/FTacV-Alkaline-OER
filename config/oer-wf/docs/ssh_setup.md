# Windows OpenSSH → WSL 直达配置指南

> 目标：让 `ssh legion "任意命令"` 直接在 WSL bash 中执行，彻底消除 Mac → Windows → WSL 三层引号嵌套。
> 推荐方案：**ForceCommand + PowerShell Shim**（不修改全局 DefaultShell，副作用最小）。

---

## 1. 问题根因（必须理解）

Windows OpenSSH 对非 `cmd.exe` 的 DefaultShell，执行远程命令时**强制追加**：

```text
<DefaultShell> <DefaultShellCommandOption> <用户命令>
```

默认 `DefaultShellCommandOption = -c`。

而 `wsl.exe` **不认识 `-c`**，收到后直接打印 help 并退出，导致 SSH 中断。

因此：

- 单纯把 `DefaultShell` 设为 `wsl.exe` → 失败
- 设 `DefaultShellCommandOption = -e bash -c` → 仍然失败（OpenSSH 还会再追加一层）

**正确做法**：让 OpenSSH 仍然调用它认识的 shell（PowerShell），再由我们的 shim 脚本把命令转交给真正的 `wsl.exe -u ... -- /bin/bash -c "..."`。

---

## 2. 推荐方案：ForceCommand + Shim（方案 A）

### 2.1 前置条件

- 已安装并启动 OpenSSH Server
- 已安装 WSL2 且至少有一个发行版
- 知道自己的：
  - Windows 用户名（`echo %USERNAME%`）
  - WSL 用户名（在 WSL 里执行 `whoami`）

### 2.2 创建 Shim 脚本

以**管理员**身份打开 PowerShell，执行：

```powershell
# 1. 创建脚本目录（如果不存在）
New-Item -ItemType Directory -Force -Path "$env:ProgramData\ssh" | Out-Null

# 2. 写入 shim
@'
param(
    [Parameter(Mandatory=$true)]
    [string]$WslUser
)

# 安全检查
if ([string]::IsNullOrWhiteSpace($WslUser)) {
    Write-Error "FATAL: -WslUser parameter is required"
    exit 1
}

# 判断是交互登录还是执行命令
if ($env:SSH_ORIGINAL_COMMAND) {
    # 非交互：执行用户命令
    # 使用 -- 防止参数被 wsl.exe 自己解析
    & wsl.exe -u $WslUser -- /bin/bash -c "$($env:SSH_ORIGINAL_COMMAND)"
    exit $LASTEXITCODE
}
else {
    # 交互登录：启动 login shell
    & wsl.exe -u $WslUser --exec /bin/bash --login
    exit $LASTEXITCODE
}
'@ | Set-Content -Path "$env:ProgramData\ssh\wsl_shim.ps1" -Encoding UTF8 -Force

# 3. 收紧权限（关键安全步骤）
icacls "$env:ProgramData\ssh\wsl_shim.ps1" /inheritance:r
icacls "$env:ProgramData\ssh\wsl_shim.ps1" /grant "SYSTEM:(RX)" /grant "BUILTIN\Administrators:(F)"
```

> 说明：脚本使用 `$env:SSH_ORIGINAL_COMMAND` 是 OpenSSH 官方推荐的可靠方式，比解析 `$args` 更稳定。

### 2.3 修改 sshd_config

以管理员身份编辑 `C:\ProgramData\ssh\sshd_config`，**在文件最末尾**添加：

```sshd_config
# ============================================================
# WSL 直达配置（oer-wf）
# 只对指定 Windows 用户生效，不影响其他账户
# ============================================================
Match User YOUR_WINDOWS_USERNAME
    ForceCommand powershell.exe -ExecutionPolicy Bypass -File "C:\ProgramData\ssh\wsl_shim.ps1" -WslUser "YOUR_WSL_USERNAME"
```

把两处占位符替换成真实值。

### 2.4 重启服务

```powershell
Restart-Service sshd
```

---

## 3. 验证清单

```bash
ssh legion "whoami && uname -a && echo \$SHELL"
ssh legion "pwd"
ssh legion 'echo "hello from WSL"'
ssh legion "echo 'single' && echo \"double\" && ls /home | head -3"
ssh legion "false"; echo $?
ssh legion "true"; echo $?
```

全部通过后，三层引号问题即宣告解决。

---

## 4. 回滚方法

```powershell
# 注释或删除 sshd_config 中的 Match 块后：
Restart-Service sshd
# 可选：
Remove-Item "$env:ProgramData\ssh\wsl_shim.ps1" -Force -ErrorAction SilentlyContinue
```

---

## 5. 与 oer-wf 的关系

配置完成后，`wf` CLI 的 `transport.py` 基于此通道实现 `ssh_exec` 与 `rsync_pull`，不再需要手工处理三层转义。

**2026-07-27 已在拯救者上部署并验证通过。**
