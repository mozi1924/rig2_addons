from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def refresh_runtime_bindings(*, logger: logging.Logger | None = None):
    """Refresh runtime-bound feature wiring after license/native state changes."""
    log = logger or _log

    try:
        from ..modules.face_cap.runtime import get_runtime_service

        get_runtime_service().refresh_backend()
    except Exception as exc:
        log.debug("Failed to refresh face_cap runtime: %s", exc)

    try:
        from ..core.utils import tag_context_redraw

        tag_context_redraw()
    except Exception as exc:
        log.debug("Failed to tag UI redraw after runtime refresh: %s", exc)
