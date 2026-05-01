# Build And Release Flow

This note keeps the local developer flow separate from addon runtime files.

## Local Native Build

Build the two managed native modules into `src/native/binaries/`:

```bash
python3 scripts/build_native.py
```

Disable ABI3 when debugging version-specific behavior:

```bash
RIG2_ENABLE_ABI3=0 python3 scripts/build_native.py
```

## Wheel Extraction

Extract native modules from CI wheels into a temporary packaging directory:

```bash
python3 scripts/extract_native_from_wheels.py --wheelhouse wheelhouse --output native_dist
```

`native_dist/` is a packaging artifact, not part of the long-lived workspace structure.

## Addon Packaging

Build the Blender addon zip into `dist/`:

```bash
python3 scripts/package_addon.py
```

The packaging script rewrites the packaged `__init__.py` so `bl_info["version"]`
is injected from the central semantic version source at build time.

CI also uploads the packaged addon zip to the Cloudflare R2 bucket
`public-assets` under the `rig2/` prefix on non-PR runs.

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
