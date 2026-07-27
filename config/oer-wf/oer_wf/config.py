"""Global configuration for oer-wf.

All machine-specific paths and connection settings live here.
Override via environment variables when needed.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Mac-side archive root
# ---------------------------------------------------------------------------
MAC_ARCHIVE_ROOT: Path = Path(
    os.environ.get("OER_WF_MAC_ARCHIVE_ROOT", Path.home() / "OER-FTAcV-archive")
)

# ---------------------------------------------------------------------------
# Remote (拯救者 / WSL) connection
# ---------------------------------------------------------------------------
SSH_HOST: str = os.environ.get("OER_WF_SSH_HOST", "legion")
SSH_USER: str = os.environ.get("OER_WF_SSH_USER", "lsy")  # Windows user that Match routes to WSL

# Absolute path of the main repo inside WSL
WSL_MAIN_REPO: Path = Path(
    os.environ.get("OER_WF_WSL_MAIN_REPO", "/home/lsy/OER-FTAcV")
)

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
SSH_TIMEOUT: int = int(os.environ.get("OER_WF_SSH_TIMEOUT", "30"))
RSYNC_TIMEOUT: int = int(os.environ.get("OER_WF_RSYNC_TIMEOUT", "600"))

# ---------------------------------------------------------------------------
# Clock skew threshold (seconds) – doctor warning
# ---------------------------------------------------------------------------
CLOCK_SKEW_WARN_SEC: float = float(os.environ.get("OER_WF_CLOCK_SKEW_WARN", "5.0"))
