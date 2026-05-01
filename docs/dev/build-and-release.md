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
