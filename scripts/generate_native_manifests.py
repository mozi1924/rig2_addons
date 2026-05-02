#!/usr/bin/env python3
"""Generate signed-manifest input files for Rig2 native licensing.

Outputs one JSON manifest per feature under:
    dist/native_manifests/<version>/<feature_id>.json

Also writes sidecar metadata next to local runtime binaries so the addon
loader can validate on-disk binaries before import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from native_artifacts import EXTENSIONS, RUNTIME_ARTIFACT_SPECS, is_sidecar_metadata
from versioning import load_version_info, semver


def _load_registry_module():
    import importlib.util

    registry_path = ROOT / "src" / "licensing" / "registry.py"
    spec = importlib.util.spec_from_file_location("rig2_generate_native_manifests_registry", registry_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _normalize_newlines_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _sha256_text_file_normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = _normalize_newlines_lf(text).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _build_sidecar_path(binary_path: Path) -> Path:
    return binary_path.with_name(binary_path.name + ".orbis.json")


def generate_manifests(output_root: Path, *, binary_dir: Path) -> list[Path]:
    registry = _load_registry_module()
    version = semver(load_version_info())
    output_dir = output_root / version
    output_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    binaries_root = binary_dir
    module_index: dict[str, str] = {}

    for spec in registry.iter_native_feature_specs():
        manifest = {
            "product_id": "rig2",
            "feature_id": spec.feature_id,
            "addon_version": version,
            "native_module": spec.native_module_name,
            "py_manifest_version": 1,
            "artifact_manifest_version": 1,
            "py_files": [],
            "artifacts": [],
        }

        for _, relative_path in spec.integrity_targets:
            source_path = ROOT / "src" / relative_path
            manifest["py_files"].append(
                {
                    "path": relative_path,
                    # Normalize LF/CRLF so grants stay portable across platforms.
                    "sha256": _sha256_text_file_normalized(source_path),
                }
            )

        for runtime_spec in RUNTIME_ARTIFACT_SPECS:
            runtime_dir = binaries_root / runtime_spec.runtime_tag
            if not runtime_dir.is_dir():
                continue
            candidates = sorted(
                (
                    path
                    for path in runtime_dir.iterdir()
                    if path.is_file()
                    and path.name.startswith(spec.native_module_name)
                    and not is_sidecar_metadata(path.name)
                    and path.suffix.lower() in EXTENSIONS
                ),
                key=lambda path: (len(path.name), path.name.lower()),
            )
            if not candidates:
                continue
            binary_path = candidates[0]
            artifact = {
                "module": spec.native_module_name,
                "platform": runtime_spec.platform,
                "arch": runtime_spec.arch,
                "artifact": runtime_spec.artifact_name,
                "artifact_key": f"rig2/{spec.native_module_name}/{runtime_spec.platform}/{runtime_spec.arch}/{runtime_spec.artifact_name}",
                "artifact_sha256": _sha256_file(binary_path),
                "artifact_size": binary_path.stat().st_size,
            }
            manifest["artifacts"].append(artifact)

            sidecar = {
                "product_id": "rig2",
                "feature_id": spec.feature_id,
                "addon_version": version,
                "artifact_manifest_version": 1,
                **artifact,
            }
            _build_sidecar_path(binary_path).write_text(
                json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        if not manifest["artifacts"]:
            raise FileNotFoundError(f"No runtime binaries found for feature '{spec.feature_id}'")

        output_path = output_dir / f"{spec.feature_id}.json"
        output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        generated.append(output_path)
        module_index[spec.native_module_name] = spec.feature_id

    index_path = output_dir / "_index.json"
    index_path.write_text(
        json.dumps({"addon_version": version, "modules": module_index}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    generated.append(index_path)

    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
      "--output-dir",
      type=Path,
      default=ROOT / "dist" / "native_manifests",
      help="Directory where manifest JSON files will be written.",
    )
    parser.add_argument(
      "--binary-dir",
      type=Path,
      default=ROOT / "src" / "native" / "binaries",
      help="Directory containing platform-tagged native binaries.",
    )
    args = parser.parse_args()

    generated = generate_manifests(
        args.output_dir.resolve(),
        binary_dir=args.binary_dir.resolve(),
    )
    for path in generated:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
