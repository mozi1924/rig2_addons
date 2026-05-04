import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from native_artifacts import MODULE_SOURCE_FILENAMES

try:
    from setuptools import Extension, setup
    _HAS_SETUPTOOLS = True
except Exception:  # Blender bundled Python may ship a partial setuptools.
    from distutils.core import Extension, setup
    _HAS_SETUPTOOLS = False

extra_compile_args = []
define_macros = []
dev_build_flag = os.environ.get("RIG2_DEV_BUILD", "0").strip().lower() in {"1", "true", "yes"}
define_macros.append(("RIG2_DEV_BUILD", "1" if dev_build_flag else "0"))
if os.name == "nt":
    # Use real MSVC optimization flags on Windows.
    extra_compile_args.extend(["/std:c++17", "/O2", "/DNDEBUG"])
    define_macros.append(("NOMINMAX", "1"))
    # Work around std::mutex crashes when the host process provides an older
    # msvcp140 runtime than the toolset used to build this extension.
    define_macros.append(("_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR", "1"))
else:
    extra_compile_args.extend(["-std=c++17", "-O3", "-DNDEBUG"])

extension_kwargs = {
    "language": "c++",
    "extra_compile_args": extra_compile_args,
    "define_macros": define_macros,
}

# ABI3 mode is enabled by default when setuptools is available.
# Set `RIG2_ENABLE_ABI3=0` to force version-specific CPython binaries.
enable_abi3 = _HAS_SETUPTOOLS and os.environ.get("RIG2_ENABLE_ABI3", "1") != "0"
if enable_abi3:
    define_macros.append(("Py_LIMITED_API", "0x03090000"))
    extension_kwargs.update(
        {
            "py_limited_api": True,
        }
    )

extensions = [
    Extension(
        module_name,
        sources=[f"src/{source_filename}"],
        **extension_kwargs,
    )
    for module_name, source_filename in MODULE_SOURCE_FILENAMES.items()
]

setup_kwargs = {}
if enable_abi3 and _HAS_SETUPTOOLS:
    setup_kwargs["options"] = {"bdist_wheel": {"py_limited_api": "cp39"}}

setup(
    name="rig2_native",
    version="0.1.0",
    description="Rig2 native backends",
    ext_modules=extensions,
    **setup_kwargs,
)
