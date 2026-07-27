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

把两处占位符替换成真实值：

| 占位符 | 示例 |
|--------|------|
| `YOUR_WINDOWS_USERNAME` | `lsy` 或 `Administrator` |
| `YOUR_WSL_USERNAME` | `lsy`（在 WSL 里 `whoami` 的结果）|

**多用户扩展**（可选）：

```sshd_config
Match User user1
    ForceCommand powershell.exe -ExecutionPolicy Bypass -File "C:\ProgramData\ssh\wsl_shim.ps1" -WslUser "wsl_user1"

Match User user2
    ForceCommand powershell.exe -ExecutionPolicy Bypass -File "C:\ProgramData\ssh\wsl_shim.ps1" -WslUser "wsl_user2"
```

### 2.4 重启服务

```powershell
Restart-Service sshd
```

确认服务正常：

```powershell
Get-Service sshd
```

---

## 3. 验证清单（必须全部通过）

在 **Mac** 上执行以下命令：

```bash
# 1. 基础身份与环境
ssh legion "whoami && uname -a && echo \$SHELL"

# 预期：
#   lsy
#   Linux ... x86_64 ... (WSL 内核)
#   /bin/bash

# 2. 简单命令
ssh legion "pwd"
ssh legion 'echo "hello from WSL"'

# 3. 带引号/管道的复杂命令（验证引号层数已消除）
ssh legion "echo 'single' && echo \"double\" && ls /home | head -3"

# 4. 交互登录
ssh legion
# 应直接进入 WSL bash 提示符，无 Windows 痕迹

# 5. 退出码传递
ssh legion "false"; echo $?
# 应输出 1

ssh legion "true"; echo $?
# 应输出 0
```

全部通过后，三层引号问题即宣告解决。

---

## 4. 回滚方法

如果出现异常，按以下步骤快速回滚：

```powershell
# 1. 注释或删除 sshd_config 中的 Match 块
# 用记事本/VS Code 打开 C:\ProgramData\ssh\sshd_config
# 把整个 Match User ... 段落删除或整行加 #

# 2. 重启服务
Restart-Service sshd

# 3.（可选）删除 shim 脚本
Remove-Item "$env:ProgramData\ssh\wsl_shim.ps1" -Force -ErrorAction SilentlyContinue
```

回滚后 SSH 行为恢复为 Windows 原生（PowerShell 或 cmd）。

---

## 5. 常见问题排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `ssh legion` 卡住或立即断开 | ForceCommand 路径错误 / 权限不足 | 检查 shim 路径与 icacls 权限 |
| 仍然出现 Windows 提示符 | Match User 用户名写错（大小写敏感） | 确认 `whoami` 在 Windows 下的精确用户名 |
| 命令执行成功但交互登录失败 | shim 中 `--login` 部分问题 | 检查 WSL 发行版是否正常、默认用户是否正确 |
| `Permission denied` | 公钥未正确配置 | 检查 `C:\ProgramData\ssh\administrators_authorized_keys` 或用户目录下的 authorized_keys |
| scp / rsync 异常 | 当前 shim 未特殊处理 scp 协议 | 如需完整 scp 支持，可扩展 shim（见下方进阶） |

---

## 6. 进阶：支持 scp / sftp（可选）

当前 shim 已能处理普通命令和交互。若需要完整的 `scp`/`sftp` 走 Linux 路径，可把 shim 升级为：

```powershell
param([string]$WslUser)

if ($env:SSH_ORIGINAL_COMMAND) {
    $cmd = $env:SSH_ORIGINAL_COMMAND

    # 简单判断是否为 scp/sftp 内部命令
    if ($cmd -match '^(scp|sftp-server)') {
        # 让 WSL 内的对应程序处理（需已安装 openssh-client）
        & wsl.exe -u $WslUser -- /bin/bash -c $cmd
    } else {
        & wsl.exe -u $WslUser -- /bin/bash -c $cmd
    }
} else {
    & wsl.exe -u $WslUser --exec /bin/bash --login
}
```

对于 `rsync` over SSH，通常直接 `rsync -e ssh ...` 即可，因为 rsync 走的是普通远程命令通道。

---

## 7. 与 oer-wf 工作流的关系

配置完成后：

```bash
# Mac 端可直接使用（只有一层引号）
ssh legion "cd /home/lsy/OER-FTAcV && git status"
ssh legion "systemctl --user status xxx"

# rsync 示例
rsync -avz --checksum \
  legion:/home/lsy/.../results/.../ \
  ~/OER-FTAcV-archive/results/.../
```

`wf` CLI 的 `transport.py` 将基于此通道实现 `ssh_exec` 与 `rsync_pull`，不再需要手工处理三层转义。

---

## 8. 安全注意事项

1. Shim 脚本权限已收紧为仅 SYSTEM + Administrators 可读执行。
2. `ForceCommand` 会覆盖用户指定的命令，这是预期行为。
3. 生产环境建议关闭密码登录，仅使用公钥：
   ```sshd_config
   PasswordAuthentication no
   PubkeyAuthentication yes
   ```
4. 定期检查 `C:\ProgramData\ssh\sshd_config` 是否被意外修改。

---

**配置完成后请立即运行第 3 节验证清单，确认全部通过后再继续实现 `wf doctor` / `wf prepare`。**
