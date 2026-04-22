"""
Python fallback entrypoints for face capture logic.

Later, these functions should become the compatibility surface shared by:
- pure Python implementations during refactor
- downloaded native extensions in release builds
"""


def backend_name():
    return "python"

