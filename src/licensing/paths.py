import os


def get_session_dir():
    """Return the directory where the license session file is stored.

    Uses the addon's native binaries directory so the session lives
    alongside other addon data. Falls back to a temp directory.
    """
    native_root = os.environ.get(
        "RIG2_NATIVE_ROOT",
        os.path.join(os.path.dirname(__file__), "..", "native", "binaries"),
    )
    normalized = os.path.normpath(native_root)
    try:
        os.makedirs(normalized, exist_ok=True)
    except OSError:
        import tempfile
        normalized = os.path.join(tempfile.gettempdir(), "rig2_addons")
        os.makedirs(normalized, exist_ok=True)
    return normalized


def get_session_path():
    """Return the full path to the license session JSON file."""
    from .config import SESSION_FILENAME
    return os.path.join(get_session_dir(), SESSION_FILENAME)
