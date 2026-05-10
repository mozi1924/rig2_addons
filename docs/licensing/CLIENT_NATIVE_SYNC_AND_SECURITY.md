# Client Native Sync & Security Profile

This document describes the client-side authorization pipeline used by Rig2
native features without any Orbisauth server protocol changes.

## 1) Main-thread Authorization State Machine

The pipeline is intentionally two-phase:

1. Background phase (network/cache only)
- warm token verification cache
- fetch trust bundle token
- fetch native grants for entitled features
- persist trust/grant material in local caches

2. Main-thread phase (native calls only)
- apply cached native grants to loaded native modules
- refresh runtime bindings and feature registration when requested

This avoids background-thread native calls while keeping startup responsive.

### Flow

```mermaid
flowchart LR
  A["Startup / Sync Now / Heartbeat Action"] --> B["Queue Background Prepare"]
  B --> C["Fetch trust bundle + native grants (cache)"]
  C --> D["Mark pending main-thread apply"]
  D --> E["Blender timer tick (main thread)"]
  E --> F["apply_native_grant per feature (cache-only)"]
  F --> G["Refresh runtime bindings / reconcile modules"]
  G --> H["Feature state converges to ready or explicit error"]
```

## 2) Security Boundary

Signature chain is unchanged:

- `trust_bundle` JWT verifies trust keys
- `native_grant` JWT verifies feature/device/expiry claims
- `py_manifest` verifies protected Python source hashes
- `artifact_manifest` verifies native binary hash + size

Policy controls:

- Compile-time macro `RIG2_DEV_BUILD=0|1` (default `0`)
- `RIG2_ENFORCE_NATIVE_LICENSE_CHAIN=1` (optional override)

Enforcement:

- `RIG2_DEV_BUILD=0`: strict grant + manifest validation is always required
- `RIG2_DEV_BUILD=1`: local development bypass for native grant/integrity checks
- `RIG2_DEV_BUILD=1` + `RIG2_ENFORCE_NATIVE_LICENSE_CHAIN=1`: strict checks are
  re-enabled for end-to-end license-chain testing

Why this is safer:

- No automatic “workspace detection” downgrade path
- Production binaries (`RIG2_DEV_BUILD=0`) cannot be switched into dev mode only
  by setting environment variables

## 3) CI Python 3.11 Alignment

Native CI build uses Python 3.11 build targets (`cp311-*`) to align with
Blender 4.5 runtime baseline while preserving `abi3` runtime compatibility.

CI also verifies wheel tags to fail fast if non-`cp311` wheels appear.

## 4) Server Compatibility

No Orbisauth API, JWT claim, or R2 key schema changes are required by this
design. All changes are client-side execution/order and profile enforcement.
