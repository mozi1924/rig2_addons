<p align="center">
<img src="assets/banner.webp" alt="Rig2 Banner" width="600px">
</p>

<h1 align="center">Rig/2 Ecosystem — Addons</h1>

<p align="center">
<strong>Rig/2 Blender Add-on Ecosystem: Facial Capture · GeckoLib Animation Export · Mine-imator Action Import</strong>
</p>

<p align="center">
<a href="https://mozi1924.com/mozi-rig/">Official Website</a> ·
<a href="https://github.com/mozi1924/mi2bl">mi2bl</a>
</p>

---

## Overview

**Rig2 Addons** is the official extension suite for [Rig/2](https://mozi1924.com/mozi-rig/)—the ultimate Minecraft character rigging solution for Blender.

The core Rig/2 assets file delivers a **zero-dependency** rigging experience featuring: an AIO "Super Shader," multi-dimensional limb systems (Steve & Alex), a 1:1 decoupled control panel, body shaping tools, and one-click switching between three foot modes. Simply append and use—no extra plugins required.

**Rig2 Addons** unlocks the full creative pipeline for Pro users, extending the Minecraft animation workflow from initial rigging to facial motion capture, middleware integration, and cross-platform export.

---

## Core Features

### 🎭 Facial Capture — Face Cap

Real-time facial motion capture integration supporting two major protocols:

- **LiveLinkFace (UDP)** — Directly receives 52-channel blendshape data streams from an iPhone running the Live Link Face app; supports zero-configuration Wi-Fi connectivity.
- **Custom WebSocket** — Supports JSON/Binary encoding, suitable for custom motion capture hardware or third-party software pipelines.

Supports multiple rig bindings, with independent Face Index configuration for each. Head rotation data and blendshape data are processed separately, allowing for independent adjustment of intensity coefficients. ### 🎬 GeckoLib Animation Export — R2BB (Rig2 to Blockbench)

Export Rig/2 skeletal animations with a single click into the **GeckoLib-compatible `.animation.json` format**, ready for direct use in Minecraft resource packs or for previewing in Blockbench. - Built-in bone mapping presets (Default, March, etc.) that automatically map Rig2 FK bones to the Mine-imator naming convention
- Support for custom mapping presets (save/load functionality)
- Independent control over axis sign inversion for rotation, translation, and scaling for each bone
- Automatic keyframe deduplication and normalization during animation export; outputs standard GeckoLib `format_version: 1.8.0` format
- Precise conversion of animation duration and keyframe timelines

### 🏗️ Mine-imator Animation Import — MIFrames

Use the [mi2bl](https://github.com/mozi1924/mi2bl) add-on to import `.miframes` / `.miobject` animation files from the Mine-imator ecosystem onto Rig/2 bones:

- Automatically bake MI bone hierarchies into Rig2 FK bone keyframes
- Supports various MI model configurations
- Imported animations integrate seamlessly with Blender's native Action system, allowing for further editing

---

## Version Comparison

| Feature | Open Edition |
|------|:-----------:|
| Rig/2 Core Rigging | ✅ |
| AIO Super Shader | ✅ |
| Multi-dimensional Limbs (Steve & Alex) | ✅ |
| Three Foot Modes | ✅ |
| Body Shaping | ✅ |
| 1:1 Control Panel | ✅ |
| **Face Capture (Face Cap)** | ✅ |
| **Advanced Facial Expression System (52 ​​Blendshapes)** | ✅ |
| **MIFrames Animation Import (.miframes)** | ✅ |
| **R2BB GeckoLib Export (.animation.json)** | ✅ |
| **Commercial Use License** | ✅ |
| **Priority Tech Support & Update Channel** | ✅ |

---

## Quick Start

### Installation

1. Download the Rig2 Addons `.zip` package (available to Pro users after purchase)
2. Open Blender 4.5+, go to **Edit → Preferences → Add-ons**
3. Click the **▼** in the top-right corner → **Install from file**, and select the downloaded `.zip` package
4. Search for **Rig2** and check the box to enable it

### Adding the Rig/2 Armature

After installing the add-on, press **Shift + A → Rig/2** in the 3D Viewport to add the Rig/2 armature to the scene. ### Using Facial Capture

1. Locate the **Face Cap** panel in the Properties panel.
2. Select a protocol: LiveLinkFace (default UDP port 11111) or WebSocket.
3. Bind the target Rig bones.
4. Open the Live Link Face app on your iPhone and enter your computer's IP address and port.

### Exporting GeckoLib Animations

1. Configure bone mapping in the **R2BB** section of the Properties panel (built-in presets are available).
2. Select the Action to export.
3. Click **Export** and choose a save path.

### Importing MI Actions

1. Ensure the [mi2bl](https://github.com/mozi1924/mi2bl) add-on is installed.
2. Select the Rig/2 armature.
3. Click **Load .miframes** and select the `.miframes` file.

---

## Technical Stack

- **Blender 4.5+** Python API
- **Native C++ Extensions**: Performance-critical modules (facial capture data parsing, action mapping, license verification) are written in C++ and distributed as CPython ABI3 binaries for Windows, macOS, and Linux.
- **Multi-language Support**: Built-in English and Simplified Chinese interfaces.

---

## Related Links

- [Rig/2 Official Website](https://mozi1924.com/mozi-rig/)
- [mi2bl — Mine-imator to Blender Bridge Add-on](https://github.com/mozi1924/mi2bl)
- [Mozi Store](https://store.mozi1924.com/)
- [YouTube Channel](https://www.youtube.com/@moziarasaka)
- [Bilibili](https://space.bilibili.com/434156493)

---

<p align="center">
<a href="assets/LICENSE">Asset files (Rig/2 Blend) are licensed under CC BY-NC-SA 4.0</a>
<br>
Copyright © 2026 <a href="https://mozi1924.com/">mozi1924</a>. All rights reserved.
</p>