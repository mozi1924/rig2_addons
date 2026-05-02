import os
import sys


def _get_default_native_root():
    return os.environ.get(
        "RIG2_NATIVE_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "native", "binaries"),
    )


def _get_blender_session_dir():
    try:
        import bpy

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
        return normalized
    raise OSError("Unable to create a writable session directory for rig2_addons")



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
