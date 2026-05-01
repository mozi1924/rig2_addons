#!/usr/bin/env python3
"""Extract rig2 native extension modules from built wheels into runtime tag folders."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

from native_artifacts import (
    EXTENSIONS,
    MODULE_NAMES,
    detect_module_name,
    map_wheel_platform_tag_to_runtime_tags,
    parse_wheel_platform_tags,
)


def iter_extension_members(zf: zipfile.ZipFile) -> list[str]:
    by_module: dict[str, str] = {}
    by_module_fallback: dict[str, str] = {}
    for member in zf.namelist():
        filename = Path(member).name
        if not filename:
            continue
        if not filename.endswith(EXTENSIONS):
            continue
        if not filename.startswith(MODULE_NAMES):
            continue
        module_name = detect_module_name(filename)
        if not module_name:
            continue
        if ".abi3." in filename:
            by_module[module_name] = member
        elif module_name not in by_module_fallback:
            by_module_fallback[module_name] = member

    merged = dict(by_module_fallback)
    merged.update(by_module)
    return [merged[key] for key in sorted(merged)]


def extract_wheel(wheel_path: Path, out_dir: Path) -> list[Path]:
    platform_tags = parse_wheel_platform_tags(wheel_path.name)
    runtime_tags = []
    for plat in platform_tags:
        runtime_tags.extend(map_wheel_platform_tag_to_runtime_tags(plat))
    runtime_tags = list(dict.fromkeys(runtime_tags))

    if not runtime_tags:
        print(f"[extract-native] skip {wheel_path.name}: unsupported platform tag(s) {platform_tags}")
        return []

    outputs: list[Path] = []
    with zipfile.ZipFile(wheel_path, "r") as zf:
        members = iter_extension_members(zf)
        if not members:
            print(f"[extract-native] skip {wheel_path.name}: no extension modules found")
            return []

        for member in members:
            payload = zf.read(member)
            basename = Path(member).name
            module_name = re.split(r"[.-]", basename, maxsplit=1)[0]
            for tag in runtime_tags:
                target_dir = out_dir / tag
                target_dir.mkdir(parents=True, exist_ok=True)

                for existing in target_dir.glob(f"{module_name}*"):
                    if existing.is_file():
                        existing.unlink()

                target_path = target_dir / basename
                target_path.write_bytes(payload)
                outputs.append(target_path)

    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True, help="Directory containing .whl files")
    parser.add_argument("--output", type=Path, required=True, help="Output root for extracted native binaries")
    args = parser.parse_args()

    wheelhouse = args.wheelhouse
    if not wheelhouse.exists():
        raise FileNotFoundError(f"wheelhouse does not exist: {wheelhouse}")

    wheels = sorted(wheelhouse.rglob("*.whl"))
    if not wheels:
        raise FileNotFoundError(f"no wheels found under: {wheelhouse}")

    total_outputs = 0
    for wheel in wheels:
        outputs = extract_wheel(wheel, args.output)
        total_outputs += len(outputs)
        for out in outputs:
            print(f"[extract-native] {wheel.name} -> {out}")

    if total_outputs == 0:
        raise RuntimeError("no native extension files were extracted from provided wheels")

    print(f"[extract-native] extracted {total_outputs} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
