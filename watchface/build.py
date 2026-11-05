#!/usr/bin/env python3
"""Build an N66 diagnostic watchface using a pinned external packer."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parent
PACKER_COMMIT = "5e4195ce91b9d8810a7a2233c96b4cba44184adc"
PACKER_URL = (
    "https://raw.githubusercontent.com/zhy8388608/Mi8WfBinTool/"
    + PACKER_COMMIT + "/Mi8WfBinTool.java"
)
FACE_ID = "975903280"


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def preview_png():
    rows = bytearray()
    for y in range(490):
        rows.append(0)
        for x in range(192):
            active = 28 <= x < 164 and 160 <= y < 330
            rows.extend((24, 56, 78) if active else (0, 0, 0))
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 192, 490, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(rows))
        + png_chunk(b"IEND", b"")
    )


def java_tool(name):
    selected = shutil.which(name)
    configured = os.environ.get("JAVA_HOME")
    candidates = ([Path(configured) / "bin" / name] if configured else [])
    candidates += [Path("/opt/homebrew/opt/openjdk@21/bin") / name]
    if selected:
        candidates.append(Path(selected))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("A JDK with java and javac is required")


def main():
    lua = (ROOT / "main.lua").read_bytes()
    output = ROOT / "Band9FindMyV5.face"
    with tempfile.TemporaryDirectory(prefix="band9-probe-build-") as temporary:
        work = Path(temporary)
        source = urllib.request.urlopen(PACKER_URL, timeout=30).read()
        original_guard = b"if (!namedFaces || hasAnyAod) {"
        if source.count(original_guard) != 1:
            raise SystemExit("Unexpected upstream unpacker implementation")
        verifier_source = source.replace(original_guard, b"if (hasAnyAod) {")
        (work / "Mi8WfBinTool.java").write_bytes(verifier_source)
        subprocess.run([java_tool("javac"), "Mi8WfBinTool.java"], cwd=work, check=True)
        images = work / "project" / "images"
        (images / "lua").mkdir(parents=True)
        (images / "lua" / "main.lua").write_bytes(lua)
        (images / "preview.png").write_bytes(preview_png())
        definition = {
            "name": "Band9FindMyV5", "id": FACE_ID, "previewImg": "preview",
            "elementsNormal": [{
                "type": "type_element_lua", "jsFileName": "lua/main.lua",
                "x": 0, "y": 0, "jsImgList": [],
            }],
            "elementsAod": [],
        }
        (work / "project" / "wfDef.json").write_text(json.dumps(definition))
        java = [java_tool("java"), "-Djava.awt.headless=true", "-cp", str(work), "Mi8WfBinTool"]
        subprocess.run(java + ["pack", str(work / "project"), str(output), "n66"], check=True)
        verification = work / "verification"
        (verification / "images" / "lua").mkdir(parents=True)
        subprocess.run(java + ["unpack", str(output), str(verification), "n66"], check=True)
        recovered = verification / "images" / "lua" / "main.lua"
        if recovered.read_bytes() != lua:
            raise SystemExit("Embedded Lua differs from the source")
        data = output.read_bytes()
        if data[:4] != bytes.fromhex("5aa53412") or struct.unpack_from("<H", data, 28)[0] != 1:
            raise SystemExit("Unexpected watchface header")
        preview_offset = struct.unpack_from("<I", data, 32)[0]
        if struct.unpack_from("<HH", data, preview_offset + 4) != (192, 490):
            raise SystemExit("Unexpected preview dimensions")
        manifest = {
            "file": output.name, "size": len(data), "watchface_id": FACE_ID,
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_sha256": hashlib.sha256(lua).hexdigest(),
            "packer_commit": PACKER_COMMIT,
            "packer_source_sha256": hashlib.sha256(source).hexdigest(),
            "verifier_patch": "Only decode an AOD face when an AOD face exists; packer code unchanged",
            "verified": ["N66 pack/unpack", "embedded Lua matches", "192x490 preview"],
            "device_tested": False,
        }
        (ROOT / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
