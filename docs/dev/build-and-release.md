# Build And Release Flow

This note keeps the local developer flow separate from addon runtime files.

## Managed Native Feature Checklist

If you add a new commercial/native module, start from
`src/licensing/registry.py` and do not stop at just C++ code.
The expected chain is:

1. Registry entry with Orbisauth/download metadata
2. Native C++ source under `native_cpp/src/`
3. Runtime integrity targets and service wiring
4. Native build/package/upload inclusion
5. CI validation via `python3 scripts/validate_feature_chain.py`

## Local Native Build

Build the three managed native modules into `src/native/binaries/`:

```bash
python3 scripts/build_native.py
```

For Blender 4.5 parity, use Python 3.11 to run the build script.

Disable ABI3 when debugging version-specific behavior:

```bash
RIG2_ENABLE_ABI3=0 python3 scripts/build_native.py
```

Enable development-profile native artifact mismatch support (local-only):

```bash
RIG2_DEV_BUILD=1 python3 scripts/build_native.py
```

## Wheel Extraction

Extract native modules from CI wheels into a temporary packaging directory:

```bash
python3 scripts/extract_native_from_wheels.py --wheelhouse wheelhouse --output native_dist
```

`native_dist/` is a packaging artifact, not part of the long-lived workspace structure.

Validate the extracted layout:

```bash
python3 scripts/verify_native_dist.py native_dist --require-complete-matrix
```

## Addon Packaging

Build the Blender addon zip into `dist/`:

```bash
python3 scripts/package_addon.py
python3 scripts/package_addon.py --compresslevel 9
```

The packaging script rewrites the packaged `__init__.py` so `bl_info["version"]`
is injected from the central semantic version source at build time.

CI also uploads the packaged addon zip to the Cloudflare R2 bucket
`public-assets` under the `rig2/` prefix on non-PR runs.

Uploaded addon objects include:

- `rig2/rig2_addons-<semver>.zip`
- `rig2/latest.zip`

## Version Management

The addon version source lives in `version.json` and is split into:

- `major`
- `minor`
- `patch`

Show the current version:

```bash
python3 scripts/versioning.py show
```

Bump a version part:

```bash
python3 scripts/versioning.py bump patch
python3 scripts/versioning.py bump minor
python3 scripts/versioning.py bump major
```

Set an explicit version:

```bash
python3 scripts/versioning.py set --major 1 --minor 2 --patch 0
```

## Integrity Hashes

Refresh generated integrity hashes before rebuilding protected native binaries:

```bash
python3 scripts/generate_integrity_hashes.py
```

## Runtime Profile

Runtime grant enforcement profile is controlled by:

- `RIG2_RUNTIME_PROFILE=prod` (default): strict artifact hash/size enforcement.
- `RIG2_DEV_BUILD=1`: local development build defaults to native grant/integrity bypass.
- `RIG2_ENFORCE_NATIVE_LICENSE_CHAIN=1`: re-enable strict native grant/integrity
  checks for end-to-end license-chain testing.

Official CI artifacts are built with `RIG2_DEV_BUILD=0`.

## R2 Upload

Upload extracted binaries to Cloudflare R2:

```bash
python3 scripts/upload_to_r2.py --binary-dir native_dist --storage-prefix rig2
```

## Cleanup

Safe to remove after local work:

- `dist/`
- `native_dist/`
- `__pycache__/`

Do not casually remove:

- `src/native/binaries/`
  Blender loads native runtime files from here during development.
