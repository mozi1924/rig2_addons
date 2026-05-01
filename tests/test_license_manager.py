import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "src" / "licensing" / "manager.py"
LICENSING_INIT_PATH = ROOT / "src" / "licensing" / "__init__.py"


def _make_session(now, *, access_exp, refresh_exp, heartbeat_interval=300, features=None):
    return types.SimpleNamespace(
        tokens=types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="Bearer",
            expires_in=max(0, int(access_exp - now)),
            refresh_expires_in=max(0, int(refresh_exp - now)),
        ),
        product="Rig2",
        tier="Pro",
        features=features or {"face_cap": True},
        heartbeat=types.SimpleNamespace(
            interval_seconds=heartbeat_interval,
            grace_period_seconds=3600,
        ),
        device_id="dev-test",
        device_name="Test Machine",
        license_id="lic-test",
        activated_at=now - 120,
        server_url="https://orbisauth.test",
    )


def _load_manager_module():
    package_name = "rig2testpkg_manager"
    module_name = f"{package_name}.licensing.manager"
    config_name = f"{package_name}.licensing.config"
    device_id_name = f"{package_name}.licensing.device_id"
    paths_name = f"{package_name}.licensing.paths"
    orbisauth_name = f"{package_name}.orbisauth"
    jwt_name = f"{package_name}.orbisauth._jwt"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    licensing_pkg = types.ModuleType(f"{package_name}.licensing")
    licensing_pkg.__path__ = []
    orbisauth_pkg = types.ModuleType(orbisauth_name)
    orbisauth_pkg.__path__ = []

    config_mod = types.ModuleType(config_name)
    config_mod.DEFAULT_SERVER_URL = "https://orbisauth.test"
    config_mod.HTTP_TIMEOUT_SECONDS = 0.1
    config_mod.REFRESH_SKEW_SECONDS = 0

    device_id_mod = types.ModuleType(device_id_name)
    device_id_mod.get_or_create_device_id = lambda: "dev-test"

    paths_mod = types.ModuleType(paths_name)
    paths_mod.get_session_path = lambda: "/tmp/rig2-test-session.json"

    class OrbisAuthError(Exception):
        pass

    class OrbisAuthTokenError(Exception):
        pass

    class FakeClient:
        default_session = None
        heartbeat_callback = staticmethod(lambda: None)

        def __init__(self, *args, **kwargs):
            self.session = type(self).default_session

        def load_session(self):
            self.session = type(self).default_session
            return self.session

        def activate(self, license_key, device_id, device_name):
            now = time.time()
            self.session = _make_session(
                now,
                access_exp=now + 900,
                refresh_exp=now + 7200,
            )
            return self.session

        def deactivate(self):
            self.session = None

        def heartbeat(self):
            type(self).heartbeat_callback()
            return types.SimpleNamespace(ok=True)

        def get_features(self):
            if self.session is None:
                raise OrbisAuthError("no session")
            return dict(getattr(self.session, "features", {}) or {})

        def request_download(self, **kwargs):
            return None

        def download_file(self, *args, **kwargs):
            return None

    jwt_mod = types.ModuleType(jwt_name)
    jwt_mod.expiry_map = {}

    def get_token_expiry(token):
        return jwt_mod.expiry_map.get(token, 0)

    jwt_mod.get_token_expiry = get_token_expiry

    orbisauth_pkg.OrbisAuthClient = FakeClient
    orbisauth_pkg.OrbisAuthError = OrbisAuthError
    orbisauth_pkg.OrbisAuthTokenError = OrbisAuthTokenError

    sys.modules[package_name] = pkg
    sys.modules[f"{package_name}.licensing"] = licensing_pkg
    sys.modules[config_name] = config_mod
    sys.modules[device_id_name] = device_id_mod
    sys.modules[paths_name] = paths_mod
    sys.modules[orbisauth_name] = orbisauth_pkg
    sys.modules[jwt_name] = jwt_mod

    spec = importlib.util.spec_from_file_location(module_name, MANAGER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, FakeClient, jwt_mod.expiry_map


def _load_licensing_init_module(manager):
    package_name = "rig2testpkg_licensing_init"
    module_name = f"{package_name}.licensing"
    manager_name = f"{package_name}.licensing.manager"
    config_name = f"{package_name}.licensing.config"
    feature_access_name = f"{package_name}.licensing.feature_access"

    for name in list(sys.modules):
        if name == package_name or name.startswith(package_name + "."):
            sys.modules.pop(name)

    pkg = types.ModuleType(package_name)
    pkg.__path__ = []
    licensing_pkg = types.ModuleType(module_name)
    licensing_pkg.__path__ = []

    manager_mod = types.ModuleType(manager_name)
    manager_mod.LicenseManager = object
    manager_mod.get_license_manager = lambda: manager

    config_mod = types.ModuleType(config_name)
    config_mod.HEARTBEAT_INTERVAL_SECONDS = 300

    feature_access_mod = types.ModuleType(feature_access_name)
    feature_access_mod.refresh_calls = 0

    def refresh_feature_runtime():
        feature_access_mod.refresh_calls += 1

    feature_access_mod.refresh_feature_runtime = refresh_feature_runtime

    sys.modules[package_name] = pkg
    sys.modules[module_name] = licensing_pkg
    sys.modules[manager_name] = manager_mod
    sys.modules[config_name] = config_mod
    sys.modules[feature_access_name] = feature_access_mod

    spec = importlib.util.spec_from_file_location(module_name, LICENSING_INIT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, feature_access_mod


class LicenseManagerTest(unittest.TestCase):
    def test_get_status_reports_dual_expiry_and_requests_overdue_heartbeat(self):
        manager_mod, fake_client_cls, expiry_map = _load_manager_module()
        fake_client_cls.default_session = None
        manager = manager_mod.LicenseManager()

        now = 2_000_000
        session = _make_session(
            now,
            access_exp=now + 1800,
            refresh_exp=now + 7200,
            heartbeat_interval=300,
        )
        manager._client.session = session
        manager._last_heartbeat_time = now - 600
        manager._last_heartbeat_attempt_time = 0
        expiry_map["access-token"] = now + 1800
        expiry_map["refresh-token"] = now + 7200

        calls = []
        manager.request_heartbeat = lambda reason, force=False, refresh_runtime=False: calls.append(
            (reason, force, refresh_runtime)
        )
        manager.is_activated = lambda: True

        with mock.patch.object(manager_mod.time, "time", return_value=now):
            status = manager.get_status()

        self.assertEqual(status["offline_valid_until"], now + 1800)
        self.assertEqual(status["offline_valid_remaining_seconds"], 1800)
        self.assertEqual(status["session_valid_until"], now + 7200)
        self.assertEqual(status["session_valid_remaining_seconds"], 7200)
        self.assertEqual(status["heartbeat_due_at"], now - 300)
        self.assertEqual(status["heartbeat_overdue_seconds"], 300)
        self.assertTrue(status["needs_heartbeat"])
        self.assertTrue(status["should_auto_heartbeat_now"])
        self.assertEqual(calls, [("status_overdue", False, False)])
        self.assertTrue(any("background sync attempt" in w["message"] for w in status["warnings"]))

    def test_request_heartbeat_deduplicates_and_marks_follow_up_actions(self):
        manager_mod, fake_client_cls, expiry_map = _load_manager_module()
        fake_client_cls.default_session = None
        manager = manager_mod.LicenseManager()

        now = time.time()
        session = _make_session(now, access_exp=now + 900, refresh_exp=now + 3600)
        manager._client.session = session
        expiry_map["access-token"] = now + 900
        expiry_map["refresh-token"] = now + 3600

        started = threading.Event()
        release = threading.Event()

        def heartbeat_callback():
            started.set()
            release.wait(1.0)

        fake_client_cls.heartbeat_callback = staticmethod(heartbeat_callback)

        self.assertTrue(manager.request_heartbeat(reason="manual_sync", force=True, refresh_runtime=True))
        self.assertTrue(started.wait(1.0))
        self.assertFalse(manager.request_heartbeat(reason="manual_sync"))
        self.assertTrue(manager.is_heartbeat_in_flight())

        release.set()
        deadline = time.time() + 1.0
        while manager.is_heartbeat_in_flight() and time.time() < deadline:
            time.sleep(0.01)

        result = manager.consume_heartbeat_result()
        actions = manager.pop_post_heartbeat_actions()

        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertEqual(manager._consecutive_heartbeat_failures, 0)
        self.assertEqual(manager._last_heartbeat_error, "")
        self.assertTrue(actions["sync_native"])
        self.assertTrue(actions["refresh_runtime"])

    def test_request_heartbeat_respects_refresh_expiry_and_failure_state(self):
        manager_mod, fake_client_cls, expiry_map = _load_manager_module()
        fake_client_cls.default_session = None
        manager = manager_mod.LicenseManager()

        now = time.time()
        session = _make_session(now, access_exp=now - 60, refresh_exp=now + 3600)
        manager._client.session = session
        expiry_map["access-token"] = now - 60
        expiry_map["refresh-token"] = now + 3600

        fake_client_cls.heartbeat_callback = staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("network down")))
        self.assertTrue(manager.request_heartbeat(reason="timer_overdue", force=True))

        deadline = time.time() + 1.0
        while manager.is_heartbeat_in_flight() and time.time() < deadline:
            time.sleep(0.01)

        result = manager.consume_heartbeat_result()
        self.assertFalse(result["ok"])
        self.assertEqual(manager._consecutive_heartbeat_failures, 1)
        self.assertEqual(manager._last_heartbeat_error, "network down")
        self.assertIsNotNone(manager._client.session)

        expired_session = _make_session(now, access_exp=now + 60, refresh_exp=now - 1)
        manager._client.session = expired_session
        expiry_map["refresh-token"] = now - 1
        self.assertFalse(manager.request_heartbeat(reason="timer_overdue", force=False))


class LicensingTimerTest(unittest.TestCase):
    def test_timer_consumes_actions_and_fast_polls_after_result(self):
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=object()),
            consume_heartbeat_result=lambda: {"ok": True},
            pop_post_heartbeat_actions=lambda: {"sync_native": True, "refresh_runtime": True},
            should_trigger_immediate_heartbeat=lambda: False,
            request_heartbeat=lambda reason: False,
            get_status=lambda: {"is_refresh_expired": False},
            is_heartbeat_in_flight=lambda: False,
        )
        licensing_mod, feature_access_mod = _load_licensing_init_module(manager)

        sync_calls = []
        licensing_mod.sync_license_to_native_modules = lambda: sync_calls.append(True)
        licensing_mod._HEARTBEAT_TIMER_ACTIVE = True

        next_interval = licensing_mod._heartbeat_timer()

        self.assertEqual(next_interval, 1.0)
        self.assertEqual(sync_calls, [True])
        self.assertEqual(feature_access_mod.refresh_calls, 1)

    def test_timer_requests_immediate_background_heartbeat_when_overdue(self):
        requests = []
        states = iter([True, True])
        manager = types.SimpleNamespace(
            _client=types.SimpleNamespace(session=object()),
            consume_heartbeat_result=lambda: None,
            pop_post_heartbeat_actions=lambda: {"sync_native": False, "refresh_runtime": False},
            should_trigger_immediate_heartbeat=lambda: next(states),
            request_heartbeat=lambda reason: requests.append(reason) or True,
            get_status=lambda: {"is_refresh_expired": False},
            is_heartbeat_in_flight=lambda: False,
        )
        licensing_mod, _feature_access_mod = _load_licensing_init_module(manager)
        licensing_mod._HEARTBEAT_TIMER_ACTIVE = True

        next_interval = licensing_mod._heartbeat_timer()

        self.assertEqual(requests, ["timer_overdue"])
        self.assertEqual(next_interval, 1.0)


if __name__ == "__main__":
    unittest.main()
