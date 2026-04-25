# Rig2 Native Migration Candidates (C++ Focus)

This note tracks what can be migrated from Python to native binaries next,
after the current `face_cap` and `miframes` wrapper direction.

## Current Status

- Native wrapper infra exists:
  - `src/native/loader.py`
  - `src/native/face_cap_wrapper.py`
  - `src/native/miframes_wrapper.py`
- `face_cap` already has service + native lock-state contract.
- `miframes` now has:
  - `src/services/miframes_service.py`
  - `src/logic/miframes/planner.py`
  - `src/native/miframes_wrapper.py` native contract entrypoint

## Immediate C++ Targets (High ROI)

1. `miframes` operation planner and mapping rules
- Python landing zone:
  - `src/logic/miframes/planner.py`
- Native contract candidate:
  - `plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)`
- Why:
  - Pure dict/list transformation, no Blender dependency.
  - High IP density (mapping rules + operation planning).

2. `face_cap` packet protocol/parser path
- Python landing zone:
  - `src/logic/face_cap/protocol.py`
  - `src/logic/face_cap/offline_loader.py`
- Why:
  - Heavy parsing/normalization logic.
  - Good anti-reverse-engineering leverage.

## Secondary C++ Targets (Medium ROI)

1. Easing/interpolation planning for MI data
- Current location:
  - transition metadata assembly in `planner.py`
  - interpolation application remains in Blender-side importer
- Suggested split:
  - native: transition curve sampling outputs
  - python: fcurve write/apply only

2. Model registry loading and normalization
- Current location:
  - `src/modules/rig_controls/miframes/configs.py`
- Suggested split:
  - move static model config into `src/logic/miframes/model_registry.py`
  - native consumes compact config blob or embedded table

## Keep In Python (Low ROI / High Coupling)

- Blender Operator/UI registration:
  - `src/modules/*/ui.py`
  - `src/modules/*/ops.py` operator classes
- Any direct `bpy` mutation:
  - `pose.bones[...]`
  - `keyframe_insert(...)`
  - `context.scene` edits

## Suggested Migration Sequence

1. Freeze `miframes` service contract and add deterministic fixture tests for planner output.
2. Implement `rig2_miframes` native module with the same `plan_miframes_keyframe_ops` signature.
3. Move/encode model mapping tables for native consumption.
4. Add entitlement/version checks in service layer before selecting native backend.
5. Repeat the same contract-hardening workflow for remaining `face_cap` parser functions.

## Risk Notes

- `configs.py` currently imports MI helpers from `mi2bl`; if `mi2bl` API changes, Python and native behavior can drift.
- To avoid drift, define a versioned schema for planner input/output (JSON-compatible primitives only).
- Keep native contract fixture tests so C++ output stays deterministic across releases.
