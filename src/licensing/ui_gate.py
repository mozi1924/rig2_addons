from __future__ import annotations


def get_license_warnings():
    try:
        from .manager import get_license_manager

        status = get_license_manager().get_status()
        return list(status.get("warnings", []))
    except Exception:
        return []


def draw_license_warnings(layout):
    warnings = get_license_warnings()
    for warning in warnings:
        row = layout.row()
        row.alert = True
        level = str(warning.get("level", "") or "").upper()
        icon = "ERROR" if level in {"ERROR", "CRITICAL"} else "WARNING"
        row.label(text=warning.get("message", ""), icon=icon)
    return bool(warnings)


def report_blocking_license_warnings(operator):
    for warning in get_license_warnings():
        level = str(warning.get("level", "") or "").upper()
        if level in {"CRITICAL", "ERROR"}:
            operator.report({"ERROR"}, warning.get("message", ""))
            return True
    return False
