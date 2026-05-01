"""On-demand native binary download via Orbisauth license server.

When a native binary is missing from the local binaries directory and the
user has an active license, this module can fetch the binary from the
Orbisauth download API (backed by Cloudflare R2).
"""

import logging
import os

_log = logging.getLogger(__name__)


def _get_platform_tag():
    """Return the platform tag expected by the download API."""
    import sys
    from .loader import get_arch_tag
    arch = get_arch_tag()
    return f"{sys.platform}-{arch}-abi3"


def _get_module_dir(module_name):
    """Return the directory where a downloaded module should be placed."""
    from .loader import get_native_root, get_abi3_platform_tag
    return os.path.join(get_native_root(), get_abi3_platform_tag())


def ensure_native_binary(module_name):
    """Ensure a native binary is available for the current platform.

    Returns True if the binary is now available (was already present,
    or was successfully downloaded). Returns False if download failed
    or the user is not licensed.

    Does NOT reload already-loaded modules — the caller must restart
    the addon or manually reload after a successful download.
    """
    from .loader import build_native_module_path

    # 1. Check if binary already exists locally.
    for path in build_native_module_path(module_name):
        if os.path.exists(path):
            return True

    # 2. Try to download via license server.
    _log.info("Native binary '%s' not found, attempting download.", module_name)
    try:
        from ..licensing.manager import get_license_manager

        mgr = get_license_manager()
        if not mgr.is_activated():
            _log.warning("Cannot download '%s': license not activated.", module_name)
            return False

        platform_tag = _get_platform_tag()
        download_info = mgr.request_download(
            module=module_name,
            platform_tag=platform_tag,
        )

        if download_info is None:
            _log.warning(
                "Download not available for '%s' on platform '%s'.",
                module_name, platform_tag,
            )
            return False

        dest_dir = _get_module_dir(module_name)
        os.makedirs(dest_dir, exist_ok=True)

        # Determine the local filename.
        # The download API returns an artifact key like "mac.dylib".
        # We need to rename it to the expected local name (e.g., "rig2_face_cap.abi3.so").
        import importlib.machinery
        suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None) or [".so", ".pyd", ".dylib"]
        dest_filename = module_name + suffixes[0]
        dest_path = os.path.join(dest_dir, dest_filename)

        mgr.download_file(download_info, dest_path)
        _log.info("Downloaded '%s' to '%s'.", module_name, dest_path)
        return os.path.exists(dest_path)

    except Exception as exc:
        _log.error("Failed to download '%s': %s", module_name, exc)
        return False


def get_download_status(module_name):
    """Return a status string describing the binary availability for UI.

    Returns:
        "available" — binary is present and loadable.
        "downloadable" — binary is missing but user has license to download.
        "unavailable" — binary is missing and user cannot download (no license).
        "unknown" — status could not be determined.
    """
    from .loader import build_native_module_path

    for path in build_native_module_path(module_name):
        if os.path.exists(path):
            return "available"

    try:
        from ..licensing.manager import get_license_manager
        mgr = get_license_manager()
        if mgr.is_activated():
            return "downloadable"
        return "unavailable"
    except Exception:
        return "unknown"
