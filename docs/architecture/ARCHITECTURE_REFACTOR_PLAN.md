# Rig2 Addon Architecture And Native Refactor Plan

## Goals

- Keep Blender-facing modules stable during commercialization.
- Isolate the parts that can be rewritten in C/Rust with minimal UI and operator churn.
- Reduce future refactor risk by defining clear boundaries between `bpy` glue code and pure logic.
- Prepare for a commercial model where advanced features depend on downloadable native binaries.

## Current Entry Flow

- Root entry: `__init__.py`
- Addon bootstrap: `src/__init__.py`
- Feature modules:
  - `src/modules/binding`
  - `src/modules/rig_controls`
  - `src/modules/face_cap`
- Shared helpers:
  - `src/core`
  - `src/ui`
  - `src/ui_shared`
  - `src/i18n`
  - `src/preferences.py`

Current registration chain:

1. Blender loads `__init__.py`
2. `src.register()` is called
3. `src/__init__.py` registers:
   - `i18n`
   - `preferences`
   - `rig_controls`
   - `face_cap`
   - `binding`
4. Each feature module registers its own `props`, `ops`, `ui`, and runtime pieces

## Current Module Responsibilities

### `src/modules/binding`

Purpose:

- Append bundled Rig2 assets from `assets/rig2-remake.blend`

Characteristics:

- Thin Blender operator layer
- Not security-sensitive
- Not worth native rewriting

Recommendation:

- Keep as Python
- Treat as stable shell module

### `src/modules/rig_controls`

Purpose:

- Rig property access and helper operators
- User-visible controls and UI
- `.miframes` import entrypoints

Subparts:

- `props.py`: Blender property definitions and model selection
- `ops.py`: reset/keyframe helper operators
- `ui.py`: Blender UI
- `miframes/importer.py`: import orchestration
- `miframes/configs.py`: model mappings and transform rules

Recommendation:

- Keep `props.py`, `ops.py`, `ui.py` in Python
- Split `miframes` into:
  - Python orchestration layer
  - pure mapping/transform engine layer suitable for native rewrite

### `src/modules/face_cap`

Purpose:

- Face capture binding management
- Live websocket receiver
- packet parsing, validation, normalization
- offline face JSON import
- runtime application to Rig2 armatures

Subparts:

- `props.py`: Blender scene properties and binding persistence
- `ops.py`: import/start/stop/apply/clear operators
- `ui.py`: Blender UI
- `runtime.py`: protocol, network, parsing, normalization, live apply loop

Recommendation:

- Highest-value native candidate
- Split protocol/parsing/data-normalization from Blender runtime apply logic

### `src/core`

Purpose:

- light shared helpers
- class registration
- constants and object checks

Recommendation:

- Keep as Python
- Expand into stable adapter utilities only

## Product Strategy Alignment

Target commercial behavior:

- The addon package includes basic features in Python.
- Core commercial logic is separated behind a wrapper boundary.
- Purchased users can pass an online entitlement check.
- After validation, the addon can download platform-specific native binaries on demand.
- If native binaries are unavailable, advanced features can stay locked or fall back to limited behavior depending on release policy.

This means the architecture should distinguish three things clearly:

1. Blender-facing feature shell
2. logic contract
3. backend implementation selected at runtime

## Main Refactor Principle

Use a strict rule:

- Anything that touches `bpy`, `bpy.types`, `context`, `pose.bones`, `keyframe_insert`, scene registration, or Blender UI stays in Python.
- Anything that only consumes plain values and returns plain values should move toward a pure logic layer.

This gives a safe long-term shape:

1. UI layer
2. Operator/application layer
3. Adapter/service layer
4. Pure logic layer
5. Optional native library implementation

## Proposed Target Structure

Recommended target layout:

```text
src/
  core/
    constants.py
    registration.py
    utils.py
    native_loader.py
    data_models.py

  services/
    face_cap_service.py
    miframes_service.py

  logic/
    face_cap/
      packet_models.py
      packet_parser.py
      schema_parser.py
      payload_normalizer.py
      offline_loader.py
      transport_types.py
    miframes/
      model_registry.py
      transform_engine.py
      frame_mapper.py
      easing_models.py

  adapters/
    blender/
      rig_access.py
      face_cap_apply.py
      keyframe_writer.py

  native/
    README.md
    binaries/
    face_cap_bridge.py
    miframes_bridge.py

  modules/
    binding/
    rig_controls/
    face_cap/
```

Notes:

- `modules/*` stays as the public Blender feature shell.
- `services/*` coordinates use cases for operators.
- `logic/*` is pure Python first, then selectively replaced by native bridges.
- `adapters/blender/*` contains the only code that talks to Blender object data.
- `native/*` is the compatibility layer that loads `.pyd` / `.so` / `.dylib`.
- Downloaded commercial binaries should live under `src/native/binaries/<platform-tag>/`.

## Wrapper-Based Backend Selection

Recommended runtime model:

1. Operators call a service module.
2. Service module calls a wrapper module.
3. Wrapper tries to load a native backend.
4. If native backend exists, use it.
5. If native backend does not exist:
   - expose a clear "locked/unavailable" state in commercial release builds

This keeps the import path stable even when the backend implementation changes later.

Suggested naming:

- wrapper modules:
  - `src/native/face_cap_wrapper.py`
  - `src/native/miframes_wrapper.py`
- downloaded binary names:
  - `rig2_face_cap`
  - `rig2_miframes`

## What We Have Already Prepared

The repository now includes the initial scaffolding for this direction:

- `src/logic/`
- `src/native/`
- `src/services/`
- wrapper modules for face capture and miframes
- a central native loader that searches for platform-specific extension modules

At this stage, behavior is unchanged because existing feature code does not yet depend on the new wrappers.

## Minimal-Move Refactor Strategy

To keep most existing files stable, reorganize in phases.

### Phase 1: Extract Pure Logic Without Changing UI

Move only logic out of existing heavy modules.

Suggested extractions from `src/modules/face_cap/runtime.py`:

- local IP normalization/discovery
- websocket frame parsing
- schema parsing
- binary packet parsing
- JSON packet sanitization
- quaternion normalization
- face payload equality checks

Suggested extractions from `src/modules/face_cap/ops.py`:

- offline JSON schema extraction
- frame extraction
- frame position normalization
- blendshape normalization
- offline payload loading

Suggested extractions from `src/modules/rig_controls/miframes/configs.py` and `importer.py`:

- axis mapping and scale rules
- rotation/position/scale transform math
- model config interpretation
- keyframe-ready output generation

At the end of Phase 1:

- Operators still call Python functions
- UI stays unchanged
- Native rewrite has a clear landing zone

### Phase 2: Introduce Service Layer

Create or fill in:

- `src/services/face_cap_service.py`
- `src/services/miframes_service.py`

Responsibilities:

- present clean methods to operators
- hide whether implementation is pure Python or native-backed
- centralize error handling and lock/unlock behavior
- become the natural place to trigger entitlement checks later

Example service boundaries:

- `parse_live_face_packet(raw_bytes, protocol, schema) -> packet`
- `load_offline_face_capture(path) -> normalized_frames`
- `map_miframes_to_rig(model_key, keyframes) -> bone_operations`

### Phase 3: Add Native Bridge

Create bridge modules:

- `src/native/face_cap_bridge.py`
- `src/native/miframes_bridge.py`

Responsibilities:

- detect platform and bundled binary name
- load native library
- marshal Python dict/list/bytes into stable FFI payloads
- validate native symbol contract and API version before use
- later coordinate with downloader and license validation

Do not let Blender UI or operators import the native library directly.

They should depend on services only.

### Phase 4: Replace Pure Logic Internals

After the service interface stabilizes:

- rewrite `logic/face_cap/*` in Rust/C
- rewrite `logic/miframes/*` in Rust/C
- keep Python wrappers unchanged where possible

## Best Native Rewrite Candidates

### Tier 1: Rewrite First

`src/modules/face_cap/runtime.py`

Best candidates:

- `_parse_packet_text`
- `parse_schema_message`
- `parse_binary_packet`
- `_sanitize_packet_payload`
- `_sanitize_head_quaternion`
- `_quaternions_close`
- `_face_payloads_equal`
- websocket frame decode helpers

Why:

- high-value protocol logic
- low Blender coupling
- performance-sensitive
- good obfuscation payoff

### Tier 2: Rewrite Next

`src/modules/face_cap/ops.py`

Best candidates:

- `_extract_schema_names`
- `_extract_video_fps`
- `_extract_faces`
- `_extract_frame_position`
- `_blendshapes_from_payload`
- `_normalize_head_quaternion`
- `_normalize_face_payload`
- `_extract_frame_payloads`
- `_load_offline_face_cap_payload`

Why:

- pure data normalization
- likely to accumulate format compatibility logic
- suitable for commercial differentiation

### Tier 3: Rewrite After Interfaces Stabilize

`src/modules/rig_controls/miframes/configs.py`
`src/modules/rig_controls/miframes/importer.py`

Best candidates:

- transform math
- mapping rule evaluation
- model template interpreter
- frame-to-bone operation planning

Keep in Python:

- `bpy.types.Operator`
- scene/object lookup
- `pose.bones[...]`
- `keyframe_insert`

## Modules That Should Stay Stable

These are good “outer shell” modules that should remain mostly unchanged during commercialization:

- `__init__.py`
- `src/__init__.py`
- `src/preferences.py`
- `src/core/registration.py`
- `src/core/utils.py`
- `src/modules/binding/ops.py`
- `src/modules/rig_controls/props.py`
- `src/modules/rig_controls/ops.py`
- `src/modules/*/ui.py`

These modules mostly define addon wiring, Blender properties, and UX.

## Recommended Dependency Direction

Keep imports flowing inward:

- `modules/*` can import `services/*`, `adapters/*`, `core/*`
- `services/*` can import `logic/*`, `native/*`, `adapters/*`, `core/*`
- `logic/*` can import `core/data_models.py` and standard library only
- `native/*` should not import Blender modules
- `adapters/blender/*` may import `bpy` but should not contain business rules

Avoid:

- `logic/*` importing `bpy`
- operator modules reaching directly into low-level protocol code
- native bridge modules knowing Blender scene internals

## Stable API Boundaries To Design Early

### Face Capture

Input:

- raw websocket text or bytes
- schema names
- offline JSON payload

Output:

- normalized packet:
  - `faces`
  - `face_count`
  - `sent_at`
  - optional diagnostics

Apply step remains Python:

- bind normalized packet to scene rigs
- write custom properties
- write head quaternion
- update Blender objects

### Miframes

Input:

- parsed MI keyframes
- selected model key
- timing/fps info

Output:

- planned bone operations:
  - target bone name
  - transform type
  - value
  - frame time
  - interpolation metadata

Apply step remains Python:

- fetch pose bones
- assign transform values
- insert keyframes
- apply interpolation

## Commercialization Notes

If the main goal is reverse-engineering resistance:

- Put protocol parsing and mapping rules in native code first.
- Avoid shipping high-value mapping templates as plain Python dicts.
- Prefer a service facade so reverse engineers do not get a single obvious Python entry file with all core logic.
- Keep lock-state behavior deterministic across all builds.
- Keep the downloader, version manifest, and entitlement response format separate from the core logic API.
- Design wrappers so the advanced feature call sites do not care whether binaries were bundled or downloaded.

This raises reverse cost without destabilizing the Blender-facing UX.

## Online Validation And Binary Download Model

Recommended shape:

1. Add a lightweight entitlement client in Python.
2. On first use of a premium feature, ask the service layer for backend readiness.
3. Service layer checks:
   - license state
   - local binary availability
   - binary version compatibility
4. If needed, download the platform-specific binary into `src/native/binaries/<platform-tag>/`
5. Wrapper loads the binary only after API version and required-symbol validation passes

Important implementation note:

- do not mix entitlement logic into low-level logic modules
- do not let operators manage download details
- keep all network/auth/update policy in a dedicated service later, for example `src/services/license_service.py`

This way:

- UI stays mostly unchanged
- feature code stays mostly unchanged
- binary delivery stays replaceable
- future anti-tamper changes do not ripple into Blender operators

## Suggested First Refactor Tasks

1. Create `src/services/face_cap_service.py` and move packet parsing entrypoints behind it.
2. Extract pure helpers from `face_cap/runtime.py` into `src/logic/face_cap/`.
3. Extract offline JSON parsing helpers from `face_cap/ops.py` into `src/logic/face_cap/offline_loader.py`.
4. Extract transform math from `rig_controls/miframes` into `src/logic/miframes/`.
5. Add `src/native/*_bridge.py` placeholders with required-symbol and API-version checks.
6. Update existing operators to call services instead of internal helper functions directly.

## Expected Result

After this reorganization:

- Blender UI and operators change very little.
- Future Rust/C rewrites are confined to a few pure logic modules.
- Most of the addon remains readable and maintainable Python.
- Commercially sensitive parts can be compiled and distributed as native binaries.
