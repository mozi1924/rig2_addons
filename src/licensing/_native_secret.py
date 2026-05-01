"""Embedded license secrets shared with native modules."""

try:
    from .registry import FEATURE_FACE_CAP, FEATURE_MIFRAMES, FEATURE_R2BB, iter_feature_specs
except ImportError:
    FEATURE_FACE_CAP = "face_cap"
    FEATURE_MIFRAMES = "miframes"
    FEATURE_R2BB = "r2bb"

    class _CompatSpec:
        def __init__(self, feature_id, shared_secret):
            self.feature_id = feature_id
            self.shared_secret = shared_secret

    _COMPAT_SPECS = (
        _CompatSpec(
            FEATURE_FACE_CAP,
            bytes.fromhex(
                "a3f7b2c9d1e458076f3219ac4b6d0e87"
                "15c2f93a8b4e7612d5a098c3f7e1b649"
            ),
        ),
        _CompatSpec(
            FEATURE_MIFRAMES,
            bytes.fromhex(
                "c8473d91e05a2f6b78d1c39e4a0b5726"
                "f9318c4d2e7a5b06f1d3c8e9a4b7f205"
            ),
        ),
        _CompatSpec(
            FEATURE_R2BB,
            bytes.fromhex(
                "4ab8f03d1c275a6eb9940d8b6f3a1245"
                "72ef39acb54168d0c2e77fab90431de6"
            ),
        ),
    )

    def iter_feature_specs():
        return _COMPAT_SPECS


FEATURE_SHARED_SECRETS = {
    spec.feature_id: spec.shared_secret
    for spec in iter_feature_specs()
}

# Compatibility exports for existing tests/tools.
FACE_CAP_SECRET = FEATURE_SHARED_SECRETS[FEATURE_FACE_CAP]
MIFRAMES_SECRET = FEATURE_SHARED_SECRETS[FEATURE_MIFRAMES]
R2BB_SECRET = FEATURE_SHARED_SECRETS[FEATURE_R2BB]
