#!/usr/bin/env python3
"""Generate shared OrbisAuth trusted-key sources for Python and native code."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://orbisauth.mozi1924.com/api/v1/jwks.json"
PY_OUTPUT = ROOT / "src" / "orbisauth" / "_trusted_keys.py"
CPP_OUTPUT = ROOT / "native_cpp" / "src" / "orbisauth_trusted_keys.h"


def _load_jwks(*, url: str, source_file: Path | None) -> dict:
    if source_file is not None:
        return json.loads(source_file.read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers={"User-Agent": "rig2-native-build/1.0"})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize(payload: dict) -> dict:
    keys = payload.get("keys", [])
    if not isinstance(keys, list) or not keys:
        raise ValueError("JWKS payload must contain a non-empty 'keys' list")
    normalized = {"keys": []}
    for item in keys:
        if not isinstance(item, dict):
            continue
        if item.get("kty") != "RSA":
            continue
        normalized["keys"].append(
            {
                "alg": str(item.get("alg", "RS256") or "RS256"),
                "e": str(item["e"]),
                "kid": str(item.get("kid", "") or ""),
                "kty": "RSA",
                "n": str(item["n"]),
                "use": str(item.get("use", "sig") or "sig"),
            }
        )
    if not normalized["keys"]:
        raise ValueError("JWKS payload contains no usable RSA keys")
    return normalized


def _write_python(payload: dict) -> None:
    body = "DEFAULT_TRUSTED_JWKS = " + json.dumps(payload, indent=4, sort_keys=True) + "\n"
    PY_OUTPUT.write_text(body, encoding="utf-8")


def _write_cpp(payload: dict) -> None:
    json_blob = json.dumps(payload, indent=2, sort_keys=True)
    body = (
        "#pragma once\n\n"
        "namespace rig2_trust {\n\n"
        "constexpr const char* kDefaultTrustedJwksJson = R\"json("
        + json_blob +
        ")json\";\n\n"
        "}  // namespace rig2_trust\n"
    )
    CPP_OUTPUT.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jwks-url", default=DEFAULT_URL, help="JWKS URL to fetch.")
    parser.add_argument("--jwks-file", type=Path, help="Read JWKS from a local file instead of the network.")
    args = parser.parse_args()

    payload = _normalize(_load_jwks(url=args.jwks_url, source_file=args.jwks_file))
    _write_python(payload)
    _write_cpp(payload)
    print(PY_OUTPUT)
    print(CPP_OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
