import logging

from ..licensing.registry import FEATURE_R2BB
from .errors import FeatureLockedError
from .native_feature_service import NativeLicensedFeatureService

_log = logging.getLogger(__name__)


class _LockedR2BBBackend:
    def __init__(self, lock_reason):
        self._lock_reason = str(lock_reason or "").strip()

    def _raise_locked(self):
        raise FeatureLockedError("R2BB", self._lock_reason)

    def normalize_mapping_entries(self, _entries):
        self._raise_locked()

    def mapping_entries_to_pairs(self, _entries):
        self._raise_locked()

    def mapping_entries_to_export_bones(self, _entries):
        self._raise_locked()

    def mapping_entries_to_export_name_map(self, _entries):
        self._raise_locked()

    def mapping_entries_to_rotation_axis_signs(self, _entries):
        self._raise_locked()

    def mapping_entries_to_transform_axis_signs(self, _entries):
        self._raise_locked()


class R2BBBackendService(NativeLicensedFeatureService):
    def __init__(self):
        super().__init__(FEATURE_R2BB, _log)

    def build_locked_backend(self, lock_reason):
        return _LockedR2BBBackend(lock_reason)

    def normalize_mapping_entries(self, entries):
        return self.call_unlocked_backend("normalize_mapping_entries", entries)

    def mapping_entries_to_pairs(self, entries):
        return self.call_unlocked_backend("mapping_entries_to_pairs", entries)

    def mapping_entries_to_export_bones(self, entries):
        return self.call_unlocked_backend("mapping_entries_to_export_bones", entries)

    def mapping_entries_to_export_name_map(self, entries):
        return self.call_unlocked_backend("mapping_entries_to_export_name_map", entries)

    def mapping_entries_to_rotation_axis_signs(self, entries):
        return self.call_unlocked_backend("mapping_entries_to_rotation_axis_signs", entries)

    def mapping_entries_to_transform_axis_signs(self, entries):
        return self.call_unlocked_backend("mapping_entries_to_transform_axis_signs", entries)


_r2bb_backend_service = R2BBBackendService()


def get_r2bb_backend_service():
    return _r2bb_backend_service
