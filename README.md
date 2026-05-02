<p align="center">
  <img src="assets/banner.webp" alt="Rig2 Binding Tool Banner" width="600px">
</p>

# Rig2 Binding Tool

Rig2 Binding Tool is a Blender addon for Rig2 armatures. This repository is also the addon root used by Blender and the VSCode Blender Development plugin, so keep the workspace root name and top-level `__init__.py` intact.

## Workspace Layout

- `__init__.py`: Blender addon entrypoint. Do not move or rename.
- `src/`: addon source package and module registration.
- `assets/`: bundled addon assets such as `rig2-remake.blend`.
- `native_cpp/`: C++ extension sources and packaging metadata.
- `scripts/`: build, extraction, integrity, and upload utilities.
- `scripts/legacy/`: archived local utilities not used by CI/release flow.
- `tests/`: runtime contract tests and perf helpers.
- `docs/architecture/`: architecture plans and long-form design notes.
- `docs/refactor/`: refactor targets, migration candidates, and optimization tasks.
- `docs/native/`: native binary build and packaging notes.
- `docs/licensing/`: Orbisauth and R2 maintenance notes.
- `docs/perf/`: raw benchmark output files.
- `docs/dev/`: developer workflow guides.

## Development

### VSCode Blender Development Symlink

This workspace is expected to be symlinked as the addon root, not just `src/`.

If Blender startup fails with `FileExistsError: ... scripts/addons/rig2_addons`, recreate the symlink:

```bash
rm "/Users/<you>/Library/Application Support/Blender/4.5/scripts/addons/rig2_addons"
ln -s "/absolute/path/to/rig2_addons" "/Users/<you>/Library/Application Support/Blender/4.5/scripts/addons/rig2_addons"
```

### Native Backends

Commercial native backends:

- `rig2_miframes`
- `rig2_face_cap`
- `rig2_r2bb`

### Adding A Managed Native Feature

Treat `[src/licensing/registry.py](/Users/jaxlocke/rig2_ecosystem/rig2_addons/src/licensing/registry.py)` as the first stop.
A new managed module is incomplete until all of these are wired:

1. Add a `FeatureSpec` with Orbisauth feature ID, download module name, integrity targets, and service getter.
2. Add `native_cpp/src/<module>.cpp`.
3. Ensure the module is picked up by native build/package/upload manifests.
4. Ensure the native module exposes `backend_name`, `apply_native_grant`, `clear_license_state`, and `get_license_status`.
5. Run `python3 scripts/validate_feature_chain.py`.

CI now runs that validator before native compilation, so partial integration should fail early.

Build locally:

```bash
python3 scripts/build_native.py
```

Disable ABI3 if needed:

```bash
RIG2_ENABLE_ABI3=0 python3 scripts/build_native.py
```

Build the distributable addon zip:

```bash
python3 scripts/package_addon.py
python3 scripts/package_addon.py --compresslevel 9
```

On GitHub Actions non-PR runs, the packaged addon zip is also uploaded to
Cloudflare R2 at `public-assets/rig2/`, including a stable
`public-assets/rig2/latest.zip` object for website downloads.

Version source is centralized in `version.json`:

```bash
python3 scripts/versioning.py show
python3 scripts/versioning.py bump patch
```

Runtime loader search order:

1. `src/native/binaries/<sys.platform>-<arch>-abi3/`
2. `src/native/binaries/<sys.platform>-abi3/`
3. `src/native/binaries/<sys.platform>-<arch>-<pyver>/`
4. `src/native/binaries/<sys.platform>-<pyver>/`

More detail:

- [Native cross-platform notes](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/native/NATIVE_CROSS_PLATFORM.md)
- [Build and release flow](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/dev/build-and-release.md)
- [Cross-addon licensing integration](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/licensing/CROSS_ADDON_INTEGRATION.md)
- [Orbisauth and R2 maintenance](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/licensing/ORBISAUTH_R2_MAINTENANCE.md)

## Cleanup Rules

Safe to clean:

- `__pycache__/`
- `.pytest_cache/`
- local `dist/`
- local wheel extraction output such as `native_dist/`

Clean with care:

- `src/native/binaries/`
  Native runtime modules live here and Blender loads directly from this tree.
- user license session directory
  The addon now prefers a per-user writable state directory for `rig2_license_session.json`, and only falls back to the addon runtime tree if needed.

## Tests

Run the contract and path tests with:

```bash
python3 -m unittest tests.test_native_contract tests.test_native_downloader tests.test_licensing_paths tests.test_license_api
```

## References

- [Architecture refactor plan](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/architecture/ARCHITECTURE_REFACTOR_PLAN.md)
- [CPP refactor targets](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/refactor/CPP_REFACTOR_TARGETS.md)
- [Migration candidates](/Users/jaxlocke/rig2_ecosystem/rig2_addons/docs/refactor/MIGRATION_CANDIDATES_CPP.md)

_Created by Antigravity_
