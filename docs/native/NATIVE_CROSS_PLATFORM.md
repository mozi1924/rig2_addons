# Native Cross-Platform Build Notes

This addon builds native backends as CPython `abi3` modules.

- CI build interpreter baseline: Python `3.11` (Blender 4.5 aligned)
- Runtime compatibility target: `abi3` (`Py3.9+`)

## Runtime Tags

Loader search order:

1. `<sys.platform>-<arch>-abi3`
2. `<sys.platform>-abi3`
3. `<sys.platform>-<arch>-<pyver>`
4. `<sys.platform>-<pyver>`

Examples:

- `darwin-arm64-abi3`
- `linux-x86_64-abi3`
- `win32-arm64-abi3`

## Local Build

```bash
python3 scripts/build_native.py
```

Outputs are copied into `src/native/binaries/<platform-arch-abi3>/`.

## CI Build Matrix

Workflow: `.github/workflows/build-native-binaries.yml`

- Linux: `x86_64`, `aarch64`
- macOS: `x86_64`, `arm64`
- Windows: `AMD64`, `ARM64`

CI builds wheels via `cibuildwheel`, then converts wheels into addon runtime folders using:

```bash
python scripts/extract_native_from_wheels.py --wheelhouse wheelhouse --output native_dist
```

Resulting `native_dist` can be published as release artifacts and copied into
`src/native/binaries/` in platform-specific packages.

## Runtime Security Profile

Native grant verification always validates JWT signatures and Python source
integrity manifests. Artifact hash/size handling is profile-based:

- `RIG2_RUNTIME_PROFILE=prod` (default): strict artifact hash + size check.
- `RIG2_RUNTIME_PROFILE=dev`: artifact mismatch is only allowed when binaries
  are compiled with `RIG2_DEV_BUILD=1`.

Official CI builds force `RIG2_DEV_BUILD=0`, so production artifacts cannot be
downgraded into dev behavior via environment variable alone.

For the full local workflow, including cleanup expectations, see
[`docs/dev/build-and-release.md`](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/dev/build-and-release.md).
