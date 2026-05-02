"""On-demand native binary download via Orbisauth license server.

When a native binary is missing from the local binaries directory and the
user has an active license, this module can fetch the binary from the
Orbisauth download API (backed by Cloudflare R2).
"""

import logging
import os
import json
import hashlib

_log = logging.getLogger(__name__)

_PENDING_CLEANUP: set[str] = set()
"""Paths that could not be removed at download time (e.g. loaded .pyd on Windows).

Call :func:`cleanup_pending_modules` early during addon startup to retry.
"""


def _sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _binary_manifest_path(module_path):
    return module_path + ".orbis.json"


def _write_binary_manifest(module_path, download_info):
    manifest = {
        "module": getattr(download_info, "module", ""),
        "artifact_key": getattr(download_info, "artifact_key", ""),
        "feature_id": getattr(download_info, "feature_id", ""),
        "addon_version": getattr(download_info, "addon_version", ""),
        "artifact_sha256": getattr(download_info, "artifact_sha256", ""),
        "artifact_size": int(getattr(download_info, "artifact_size", 0) or 0),
        "artifact_manifest_version": int(getattr(download_info, "artifact_manifest_version", 0) or 0),
        "signed_artifact_manifest": getattr(download_info, "signed_artifact_manifest", ""),
    }
    manifest_path = _binary_manifest_path(module_path)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _validate_downloaded_artifact(temp_path, download_info):
    expected_size = int(getattr(download_info, "artifact_size", 0) or 0)
    expected_sha = str(getattr(download_info, "artifact_sha256", "") or "")
    if expected_size:
        actual_size = os.path.getsize(temp_path)
        if actual_size != expected_size:
            raise ValueError(
                f"Downloaded artifact size mismatch: expected {expected_size}, got {actual_size}"
            )
    if expected_sha:
        actual_sha = _sha256_file(temp_path)
        if actual_sha != expected_sha:
            raise ValueError(
                "Downloaded artifact digest mismatch. "
                f"Expected {expected_sha}, got {actual_sha}"
            )


def _get_platform_tag():
    """Return the platform tag expected by the download API."""
    from .loader import PlatformTarget
    return PlatformTarget.current().abi3_tag


def _get_download_request_variants():
    """Return download request variants for current platform.

    We prefer the explicit artifact path that mirrors the R2 object key,
    then keep older request shapes as compatibility fallbacks.
    """
    from .loader import PlatformTarget

    target = PlatformTarget.current()
    variants = []
    if target.platform_name:
        variants.append(
            {
                "platform_tag": target.platform_name,
                "arch": target.arch_name,
                "artifact": "",
            }
        )
    if target.artifact_name:
        variants.append(
            {
                "platform_tag": target.platform_name,
                "arch": target.arch_name,
                "artifact": target.artifact_name,
            }
        )
    variants.append(
        {
            "platform_tag": target.abi3_tag,
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
        except PermissionError:
            _log.warning("Cannot remove loaded native module '%s'; scheduled for cleanup on next startup.", path)
            _PENDING_CLEANUP.add(path)
        except OSError as exc:
            _log.warning("Cannot remove native module '%s': %s", path, exc)
    return removed


def cleanup_pending_modules():
    """Remove native module files that were scheduled for deferred cleanup.

    Safe to call at addon startup before any native modules are loaded.
    """
    if not _PENDING_CLEANUP:
        return
    pending = list(_PENDING_CLEANUP)
    _PENDING_CLEANUP.clear()
    for path in pending:
        try:
            os.remove(path)
            _log.info("Cleaned up pending module: %s", path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log.debug("Deferred cleanup still cannot remove '%s': %s", path, exc)


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
        _validate_downloaded_artifact(temp_path, download_info)
        os.replace(temp_path, dest_path)
        _write_binary_manifest(dest_path, download_info)
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
