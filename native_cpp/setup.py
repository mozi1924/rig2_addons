import os

try:
    from setuptools import Extension, setup
except Exception:  # Blender bundled Python may ship a partial setuptools.
    from distutils.core import Extension, setup

extra_compile_args = ["-O3"]
if os.name == "nt":
    extra_compile_args.extend(["/std:c++17"])
else:
    extra_compile_args.extend(["-std=c++17"])

extensions = [
    Extension(
        "rig2_miframes",
        sources=["src/rig2_miframes.cpp"],
        language="c++",
        extra_compile_args=extra_compile_args,
    ),
    Extension(
        "rig2_face_cap",
        sources=["src/rig2_face_cap.cpp"],
        language="c++",
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="rig2_native",
    version="0.1.0",
    description="Rig2 native backends",
    ext_modules=extensions,
)
