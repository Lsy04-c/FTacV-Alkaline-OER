"""Helpers for building unified WfResponse objects."""

from __future__ import annotations

from typing import Any, Optional

from oer_wf.models import CheckResult, FailType, StatusEnum, WfResponse


def ok(
    message: str = "",
    next_action: str = "",
    data: Optional[dict[str, Any]] = None,
    checks: Optional[list[CheckResult]] = None,
) -> WfResponse:
    return WfResponse(
        status=StatusEnum.PASS,
        fail_type=FailType.NULL,
        checks=checks or [],
        data=data or {},
        next_action=next_action,
        message=message,
    )


def fail(
    fail_type: FailType,
    message: str,
    next_action: str = "",
    data: Optional[dict[str, Any]] = None,
    checks: Optional[list[CheckResult]] = None,
) -> WfResponse:
    return WfResponse(
        status=StatusEnum.FAIL,
        fail_type=fail_type,
        checks=checks or [],
        data=data or {},
        next_action=next_action,
        message=message,
    )


def warning(
    message: str,
    next_action: str = "",
    data: Optional[dict[str, Any]] = None,
    checks: Optional[list[CheckResult]] = None,
) -> WfResponse:
    return WfResponse(
        status=StatusEnum.WARNING,
        fail_type=FailType.NULL,
        checks=checks or [],
        data=data or {},
        next_action=next_action,
        message=message,
    )


def running(
    message: str = "",
    next_action: str = "",
    data: Optional[dict[str, Any]] = None,
    checks: Optional[list[CheckResult]] = None,
) -> WfResponse:
    return WfResponse(
        status=StatusEnum.RUNNING,
        fail_type=FailType.NULL,
        checks=checks or [],
        data=data or {},
        next_action=next_action,
        message=message,
    )
