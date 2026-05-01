# Native Cross-Platform Build Notes

This addon now builds native backends as CPython `abi3` modules (target: `Py3.9+`).

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

Outputs are copied into `src/native/binaries/*` for both new and legacy tag formats.

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

For the full local workflow, including cleanup expectations, see
[`docs/dev/build-and-release.md`](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/dev/build-and-release.md).
