import os

try:
    from setuptools import Extension, setup
    _HAS_SETUPTOOLS = True
except Exception:  # Blender bundled Python may ship a partial setuptools.
    from distutils.core import Extension, setup
    _HAS_SETUPTOOLS = False

extra_compile_args = ["-O3"]
define_macros = []
if os.name == "nt":
    extra_compile_args.extend(["/std:c++17"])
    define_macros.append(("NOMINMAX", "1"))
else:
    extra_compile_args.extend(["-std=c++17"])

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
        "rig2_miframes",
        sources=["src/rig2_miframes.cpp"],
        **extension_kwargs,
    ),
    Extension(
        "rig2_face_cap",
        sources=["src/rig2_face_cap.cpp"],
        **extension_kwargs,
    ),
    Extension(
        "rig2_r2bb",
        sources=["src/rig2_r2bb.cpp"],
        **extension_kwargs,
    ),
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
