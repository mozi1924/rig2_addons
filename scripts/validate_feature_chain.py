#!/usr/bin/env python3
"""Fail-fast validation for the managed native feature integration chain.

This script exists to make new commercial/native modules hard to add partially.
If a feature is registered for licensing, we also expect:
1. a native C++ source file
2. inclusion in native build/package/upload manifests
3. download metadata for Orbisauth-delivered binaries
4. required native license/integrity hooks
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from native_artifacts import MANAGED_NATIVE_FEATURES, MODULE_NAMES, MODULE_SOURCE_FILENAMES


ROOT = Path(__file__).resolve().parents[1]
NATIVE_CPP_SRC = ROOT / "native_cpp" / "src"
SETUP_PY = ROOT / "native_cpp" / "setup.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build-native-binaries.yml"
REQUIRED_NATIVE_CALLABLES = frozenset({"backend_name", "set_license_state", "verify_integrity"})


def _load_registry_module():
    registry_path = ROOT / "src" / "licensing" / "registry.py"
    spec = importlib.util.spec_from_file_location("rig2_validate_feature_chain_registry", registry_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_feature_chain() -> list[str]:
    errors: list[str] = []
    setup_text = SETUP_PY.read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    registry = _load_registry_module()
    registry_specs = {spec.feature_id: spec for spec in registry.iter_native_feature_specs()}

    if "scripts/validate_feature_chain.py" not in workflow_text:
        errors.append("CI workflow does not run scripts/validate_feature_chain.py")
    if "MODULE_SOURCE_FILENAMES" not in setup_text:
        errors.append("native_cpp/setup.py must build extensions from shared MODULE_SOURCE_FILENAMES manifest")

    for feature in MANAGED_NATIVE_FEATURES:
        spec = registry_specs[feature.feature_id]
        module_name = feature.native_module_name
        if feature.download_module_name != module_name:
            errors.append(
                f"{feature.feature_id}: download_module_name must match native_module_name ({module_name})"
            )
        if module_name not in MODULE_NAMES:
            errors.append(f"{feature.feature_id}: {module_name} missing from managed module manifest")

        source_name = MODULE_SOURCE_FILENAMES.get(module_name, "")
        if source_name != feature.native_source_filename:
            errors.append(
                f"{feature.feature_id}: manifest/source mismatch for {module_name} ({source_name!r})"
            )

        source_path = NATIVE_CPP_SRC / feature.native_source_filename
        if not source_path.is_file():
            errors.append(f"{feature.feature_id}: missing native source file {source_path}")

        service_getter = feature.service_getter
        if ":" not in service_getter or not service_getter.split(":", 1)[1].startswith("get_"):
            errors.append(f"{feature.feature_id}: suspicious service_getter {service_getter!r}")
        missing_callables = REQUIRED_NATIVE_CALLABLES - set(spec.required_callables)
        if missing_callables:
            errors.append(
                f"{feature.feature_id}: required_callables missing {sorted(missing_callables)!r}"
            )
        if not spec.shared_secret:
            errors.append(f"{feature.feature_id}: shared_secret must not be empty")
        if not spec.integrity_targets:
            errors.append(f"{feature.feature_id}: integrity_targets must not be empty")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    errors = validate_feature_chain()
    if errors:
        raise SystemExit("Invalid managed native feature chain:\n" + "\n".join(errors))

    print("[validate-feature-chain] OK")
    print("[validate-feature-chain] Adding a new managed native feature requires:")
    print("  - registry entry with Orbisauth/download metadata")
    print("  - native_cpp/src/<module>.cpp")
    print("  - native build/package/upload manifests")
    print("  - native license hooks: backend_name, set_license_state, verify_integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
