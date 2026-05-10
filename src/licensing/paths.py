import os
import sys


def _get_default_native_root():
    return os.environ.get(
        "RIG2_NATIVE_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "native", "binaries"),
    )


def _resolve_addon_module_name():
    """
    Resolve addon module name from this submodule package.

    Examples:
      rig2_addons.src.licensing -> rig2_addons
      bl_ext.repo.rig2_addons.src.licensing -> bl_ext.repo.rig2_addons
    """
    package_name = __package__ or ""
    marker = ".src."
    if marker in package_name:
        return package_name.split(marker, 1)[0]
    if package_name.endswith(".src"):
        return package_name[: -len(".src")]
    return "rig2_addons"


def _get_legacy_config_dir():
    try:
        import bpy

        path = bpy.utils.user_resource("CONFIG", path="rig2_addons", create=False)
        if path:
            return path
    except Exception:
        pass

    home = os.path.expanduser("~")
    if os.name == "nt":
        base_dir = os.environ.get("APPDATA") or home
        return os.path.join(base_dir, "rig2_addons")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "Blender", "config", "rig2_addons")
    base_dir = os.environ.get("XDG_CONFIG_HOME")
    if not base_dir:
        base_dir = os.path.join(home, ".config")
    return os.path.join(base_dir, "rig2_addons")


def _get_blender_session_dir():
    try:
        import bpy
        package_name = _resolve_addon_module_name()
        # Blender 4.2+ extension storage path (preferred).
        if package_name:
            extension_path_user = getattr(bpy.utils, "extension_path_user", None)
            if callable(extension_path_user):
                path = extension_path_user(package_name, path="", create=False)
                if path:
                    return path
        # Legacy addon fallback path.
        path = bpy.utils.user_resource("CONFIG", path="rig2_addons", create=False)
        if path:
            return path
    except Exception:
        return ""
    return ""


def _get_user_state_dir():
    override = os.environ.get("RIG2_SESSION_DIR")
    if override:
        return override

    blender_dir = _get_blender_session_dir()
    if blender_dir:
        return blender_dir

    home = os.path.expanduser("~")
    if os.name == "nt":
        base_dir = os.environ.get("APPDATA") or home
        return os.path.join(base_dir, "rig2_addons")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "rig2_addons")

    base_dir = os.environ.get("XDG_STATE_HOME")
    if not base_dir:
        base_dir = os.environ.get("XDG_CONFIG_HOME")
    if not base_dir:
        base_dir = os.path.join(home, ".local", "state")
    return os.path.join(base_dir, "rig2_addons")


def _iter_session_dir_candidates():
    yield _get_user_state_dir()
    yield _get_default_native_root()

    import tempfile

    yield os.path.join(tempfile.gettempdir(), "rig2_addons")


def get_session_dir():
    """Return the directory where the license session file is stored.

    Prefer a per-user writable state directory. If that is unavailable,
    fall back to the addon's native runtime directory, then the temp dir.
    """
    for candidate in _iter_session_dir_candidates():
        normalized = os.path.normpath(candidate)
        try:
            os.makedirs(normalized, exist_ok=True)
            # Test if the directory is actually writable
            test_file = os.path.join(normalized, ".rig2_write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except (OSError, PermissionError):
            continue
        _migrate_legacy_session_files_if_needed(normalized)
        return normalized
    raise OSError("Unable to create a writable session directory for rig2_addons")


def _migrate_legacy_session_files_if_needed(target_dir):
    """
    One-way best-effort migration from legacy config dir into extension dir.
    Only copies files when target file does not already exist.
    """
    try:
        from .config import (
            FEATURE_STATUS_FILENAME,
            NATIVE_GRANT_CACHE_FILENAME,
            SESSION_FILENAME,
            TRUST_BUNDLE_FILENAME,
        )
    except Exception:
        return

    source_dir = _get_legacy_config_dir()
    if not source_dir or os.path.normpath(source_dir) == os.path.normpath(target_dir):
        return

    for filename in (
        SESSION_FILENAME,
        FEATURE_STATUS_FILENAME,
        TRUST_BUNDLE_FILENAME,
        NATIVE_GRANT_CACHE_FILENAME,
    ):
        src = os.path.join(source_dir, filename)
        dst = os.path.join(target_dir, filename)
        if not os.path.isfile(src) or os.path.exists(dst):
            continue
        try:
            with open(src, "rb") as in_f:
                data = in_f.read()
            with open(dst, "wb") as out_f:
                out_f.write(data)
        except Exception:
            # Keep startup resilient: migration must never block addon runtime.
            continue



def get_session_path():
    """Return the full path to the license session JSON file."""
    from .config import SESSION_FILENAME
    return os.path.join(get_session_dir(), SESSION_FILENAME)


def get_feature_status_path():
    """Return the full path to the persisted feature status JSON file."""
    from .config import FEATURE_STATUS_FILENAME
    return os.path.join(get_session_dir(), FEATURE_STATUS_FILENAME)


def get_trust_bundle_path():
    """Return the full path to the persisted trust bundle JSON file."""
    from .config import TRUST_BUNDLE_FILENAME
    return os.path.join(get_session_dir(), TRUST_BUNDLE_FILENAME)


def get_native_grant_cache_path():
    """Return the full path to the persisted native grant cache JSON file."""
    from .config import NATIVE_GRANT_CACHE_FILENAME
    return os.path.join(get_session_dir(), NATIVE_GRANT_CACHE_FILENAME)
