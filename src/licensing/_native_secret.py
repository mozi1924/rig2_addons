"""Embedded license secrets shared with native modules.

Each native module has an embedded 32-byte secret used for HMAC
verification of license state. The corresponding secret here allows
the Python layer to produce valid HMAC proofs.

These are NOT cryptographic keys — they are shared secrets that raise
the bar for bypassing license checks by requiring coordination between
the Python and C++ layers.

If either secret is rotated, the corresponding C++ source must be
recompiled with the new value.
"""

FACE_CAP_SECRET = bytes.fromhex(
    "a3f7b2c9d1e458076f3219ac4b6d0e87"
    "15c2f93a8b4e7612d5a098c3f7e1b649"
)

MIFRAMES_SECRET = bytes.fromhex(
    "c8473d91e05a2f6b78d1c39e4a0b5726"
    "f9318c4d2e7a5b06f1d3c8e9a4b7f205"
)
