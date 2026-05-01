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


def _get_download_request_variants():
    """Return download request variants for current platform.

    We prefer the explicit artifact path that mirrors the R2 object key,
    then keep older request shapes as compatibility fallbacks.
    """
    import sys
    from .loader import get_arch_tag

    platform_name = {
        "darwin": "mac",
        "linux": "linux",
        "win32": "win",
    }.get(sys.platform, sys.platform)
    arch_name = {
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(get_arch_tag(), get_arch_tag())
    artifact_name = {
        "mac": "mac.dylib",
        "linux": "linux.so",
        "win": "win.dll",
    }.get(platform_name, "")
    variants = []
    if platform_name:
        variants.append(
            {
                "platform_tag": platform_name,
                "arch": arch_name,
                "artifact": "",
            }
        )
    if artifact_name:
        variants.append(
            {
                "platform_tag": platform_name,
                "arch": arch_name,
                "artifact": artifact_name,
            }
        )
    variants.append(
        {
            "platform_tag": _get_platform_tag(),
            "arch": "",
            "artifact": "",
        }
    )
    return variants


def _get_module_dir(module_name):
    """Return the directory where a downloaded module should be placed."""
    from .loader import get_native_root, get_abi3_platform_tag
    return os.path.join(get_native_root(), get_abi3_platform_tag())


def _remove_existing_module_variants(module_name):
    from .loader import list_existing_native_module_paths

    removed = []
    for path in list_existing_native_module_paths(module_name):
        try:
            os.remove(path)
            removed.append(path)
        except FileNotFoundError:
            continue
    return removed


def ensure_native_binary(module_name, force=False):
    """Ensure a native binary is available for the current platform.

    Returns True if the binary is now available (was already present,
    or was successfully downloaded). Returns False if download failed
    or the user is not licensed.

    Callers should refresh wrapper/runtime state after a successful download
    so the newly downloaded module becomes available immediately.
    """
    from .loader import build_native_module_path

    # 1. Check if binary already exists locally.
    for path in build_native_module_path(module_name):
        if os.path.exists(path) and not force:
            return True

    # 2. Try to download via license server.
    _log.info("Native binary '%s' not found, attempting download.", module_name)
    try:
        from ..licensing.manager import get_license_manager

        mgr = get_license_manager()
        if not mgr.is_activated():
            _log.warning("Cannot download '%s': license not activated.", module_name)
            return False

        download_info = None
        last_error = None
        for request_args in _get_download_request_variants():
            try:
                download_info = mgr.request_download(
                    module=module_name,
                    platform_tag=request_args["platform_tag"],
                    arch=request_args["arch"],
                    artifact=request_args["artifact"],
                )
            except Exception as exc:
                last_error = exc
                _log.warning(
                    "Download request failed for '%s' via platform=%r arch=%r artifact=%r: %s",
                    module_name,
                    request_args["platform_tag"],
                    request_args["arch"],
                    request_args["artifact"],
                    exc,
                )
                continue
            if download_info is not None:
                break

        if download_info is None:
            if last_error is not None:
                raise last_error
            _log.warning("Download not available for '%s'.", module_name)
            return False

        dest_dir = _get_module_dir(module_name)
        os.makedirs(dest_dir, exist_ok=True)

        # Determine the local filename.
        # The download API returns an artifact key like "mac.dylib".
        # We need to rename it to the canonical local name (e.g., "rig2_face_cap.abi3.so").
        from .loader import get_preferred_extension_suffix

        dest_filename = module_name + get_preferred_extension_suffix()
        dest_path = os.path.join(dest_dir, dest_filename)
        temp_path = dest_path + ".part"

        _remove_existing_module_variants(module_name)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        mgr.download_file(download_info, temp_path)
        os.replace(temp_path, dest_path)
        _log.info("Downloaded '%s' to '%s'.", module_name, dest_path)
        return os.path.exists(dest_path)

    except Exception as exc:
        if "temp_path" in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        _log.error("Failed to download '%s': %s", module_name, exc)
        raise


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
