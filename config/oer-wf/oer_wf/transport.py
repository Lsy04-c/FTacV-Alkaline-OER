"""Transport abstraction: Executor Protocol + Real / Mock implementations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from oer_wf import config


@dataclass
class ExecResult:
    """Result of a remote or local command execution."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    cmd: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def raise_if_failed(self, msg: str = "") -> None:
        if not self.ok:
            raise RuntimeError(
                f"{msg or 'command failed'} (rc={self.returncode})\n"
                f"cmd: {self.cmd}\n"
                f"stderr: {self.stderr}"
            )


@runtime_checkable
class Executor(Protocol):
    """Dependency-injection boundary for all remote operations."""

    def ssh_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        """Run a command inside WSL via SSH. Returns structured result."""
        ...

    def rsync_pull(
        self,
        remote_path: str,
        local_path: str,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        """Pull a remote directory/file to local via rsync over SSH."""
        ...

    def local_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        """Run a command on the local machine (Mac)."""
        ...


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------

class RealExecutor:
    def __init__(
        self,
        host: str = config.SSH_HOST,
        user: str = config.SSH_USER,
        ssh_timeout: int = config.SSH_TIMEOUT,
        rsync_timeout: int = config.RSYNC_TIMEOUT,
    ):
        self.host = host
        self.user = user
        self.ssh_timeout = ssh_timeout
        self.rsync_timeout = rsync_timeout
        self._target = f"{user}@{host}" if user else host

    def ssh_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        t = timeout if timeout is not None else self.ssh_timeout
        # Because ForceCommand already lands us in WSL bash, we pass the
        # command as a single argument; only one layer of quoting is needed.
        full = ["ssh", self._target, cmd]
        try:
            proc = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=t,
            )
            return ExecResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                cmd=" ".join(full),
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                returncode=124,
                stdout=e.stdout or "" if isinstance(e.stdout, str) else "",
                stderr=f"timeout after {t}s",
                cmd=" ".join(full),
            )

    def rsync_pull(
        self,
        remote_path: str,
        local_path: str,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        t = timeout if timeout is not None else self.rsync_timeout
        # --checksum forces content comparison; --partial allows resume;
        # --no-times avoids spurious re-transfers due to filesystem time precision.
        full = [
            "rsync",
            "-avz",
            "--checksum",
            "--partial",
            "--no-times",
            f"{self._target}:{remote_path}",
            local_path,
        ]
        try:
            proc = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=t,
            )
            return ExecResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                cmd=" ".join(full),
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                returncode=124,
                stderr=f"rsync timeout after {t}s",
                cmd=" ".join(full),
            )

    def local_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        t = timeout if timeout is not None else self.ssh_timeout
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=t,
            )
            return ExecResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                cmd=cmd,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                returncode=124,
                stderr=f"local timeout after {t}s",
                cmd=cmd,
            )


# ---------------------------------------------------------------------------
# Mock implementation (for unit tests)
# ---------------------------------------------------------------------------

@dataclass
class MockExecutor:
    """Pre-programmed responses for unit tests.

    Usage:
        mock = MockExecutor()
        mock.when_ssh("git status").returns(0, "clean")
        mock.when_ssh("date -u").returns(0, "Mon Jul 27 08:00:00 UTC 2026")
    """

    _ssh_rules: list[tuple[str, ExecResult]] = field(default_factory=list)
    _rsync_rules: list[tuple[str, ExecResult]] = field(default_factory=list)
    _local_rules: list[tuple[str, ExecResult]] = field(default_factory=list)
    call_log: list[str] = field(default_factory=list)

    # ---- fluent builders ----

    def when_ssh(self, pattern: str) -> "_RuleBuilder":
        return _RuleBuilder(self, "ssh", pattern)

    def when_rsync(self, pattern: str) -> "_RuleBuilder":
        return _RuleBuilder(self, "rsync", pattern)

    def when_local(self, pattern: str) -> "_RuleBuilder":
        return _RuleBuilder(self, "local", pattern)

    def _add_rule(self, kind: str, pattern: str, result: ExecResult) -> None:
        store = {
            "ssh": self._ssh_rules,
            "rsync": self._rsync_rules,
            "local": self._local_rules,
        }[kind]
        store.append((pattern, result))

    def _match(self, rules: list[tuple[str, ExecResult]], cmd: str) -> ExecResult:
        for pattern, result in rules:
            if pattern in cmd or pattern == "*":
                return result
        return ExecResult(returncode=1, stderr=f"MockExecutor: no rule for: {cmd}", cmd=cmd)

    # ---- Protocol methods ----

    def ssh_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        self.call_log.append(f"ssh:{cmd}")
        return self._match(self._ssh_rules, cmd)

    def rsync_pull(
        self,
        remote_path: str,
        local_path: str,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        key = f"{remote_path}->{local_path}"
        self.call_log.append(f"rsync:{key}")
        return self._match(self._rsync_rules, key)

    def local_exec(self, cmd: str, timeout: Optional[int] = None) -> ExecResult:
        self.call_log.append(f"local:{cmd}")
        return self._match(self._local_rules, cmd)


class _RuleBuilder:
    def __init__(self, parent: MockExecutor, kind: str, pattern: str):
        self._parent = parent
        self._kind = kind
        self._pattern = pattern

    def returns(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> MockExecutor:
        self._parent._add_rule(
            self._kind,
            self._pattern,
            ExecResult(returncode=returncode, stdout=stdout, stderr=stderr, cmd=self._pattern),
        )
        return self._parent
