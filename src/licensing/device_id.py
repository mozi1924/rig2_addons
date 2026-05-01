"""Stable device identity using system-native machine IDs.

Priority order per platform:
- macOS: IOPlatformUUID (survives OS reinstalls on same hardware)
- Linux: /etc/machine-id or /var/lib/dbus/machine-id
- Windows: MachineGuid from registry
- Fallback: persistent random UUID in Blender config directory

All successful reads are persisted to Blender's user config so the ID
survives addon reinstallation and Blender version upgrades.
"""

import hashlib
import logging
import os
import platform
import subprocess
import sys

_log = logging.getLogger(__name__)

_PERSIST_FILENAME = "rig2_device_id"


def _blender_config_dir():
    """Return the Blender user config directory, or None if unavailable."""
    try:
        import bpy
        return bpy.utils.user_resource("CONFIG")
    except Exception:
        return None


def _read_persisted_id():
    """Read a previously persisted device ID from Blender's config dir."""
    conf = _blender_config_dir()
    if not conf:
        return None
    path = os.path.join(conf, _PERSIST_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
            if len(raw) >= 16:
                return raw
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return None


def _write_persisted_id(device_id):
    """Persist the device ID to Blender's config dir."""
    conf = _blender_config_dir()
    if not conf:
        return
    path = os.path.join(conf, _PERSIST_FILENAME)
    try:
        os.makedirs(conf, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(device_id)
    except (PermissionError, OSError) as exc:
        _log.warning("Could not persist device ID: %s", exc)


def _macos_ioplatform_uuid():
    """Read IOPlatformUUID via ioreg (macOS only)."""
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                # Extract the quoted string value
                parts = line.split('"')
                for i, part in enumerate(parts):
                    if "IOPlatformUUID" in part and i + 2 < len(parts):
                        uuid_val = parts[i + 2].strip()
                        if uuid_val:
                            return uuid_val
    except Exception as exc:
        _log.debug("ioreg failed: %s", exc)
    return None


def _linux_machine_id():
    """Read /etc/machine-id or /var/lib/dbus/machine-id (Linux only)."""
    paths = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
                if raw:
                    return raw
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return None


def _windows_machine_guid():
    """Read MachineGuid from Windows registry."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        if value:
            return str(value)
    except Exception as exc:
        _log.debug("MachineGuid read failed: %s", exc)
    return None


def _compute_derived_id(raw_system_id, salt="rig2-device-v1"):
    """Derive a fixed-length, privacy-safe device ID from a raw system ID."""
    h = hashlib.sha256()
    h.update(raw_system_id.encode("utf-8"))
    h.update(salt.encode("utf-8"))
    return h.hexdigest()[:16]


def _get_system_native_id():
    """Return a raw system-native machine identifier, or None."""
    system = platform.system()
    if system == "Darwin":
        return _macos_ioplatform_uuid()
    elif system == "Linux":
        return _linux_machine_id()
    elif system == "Windows":
        return _windows_machine_guid()
    return None


def get_or_create_device_id():
    """Return a stable device identifier.

    Resolution order:
    1. Previously persisted ID in Blender config (survives everything)
    2. System-native machine ID (IOPlatformUUID / machine-id / MachineGuid)
    3. Fallback: new random UUID persisted to Blender config
    """

    # 1. Try the persisted ID first — this is the most stable source.
    persisted = _read_persisted_id()
    if persisted:
        return persisted

    # 2. Try the system-native machine ID.
    native = _get_system_native_id()
    if native:
        device_id = _compute_derived_id(native)
        _write_persisted_id(device_id)
        return device_id

    # 3. Fallback: generate a new random ID and persist it.
    import uuid
    device_id = uuid.uuid4().hex[:16]
    _write_persisted_id(device_id)
    _log.warning("Using fallback random device ID: %s", device_id)
    return device_id
