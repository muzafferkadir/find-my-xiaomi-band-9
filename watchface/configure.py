#!/usr/bin/env python3
"""Render a personalized watchface without embedding private key material."""
import argparse
import base64
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser()
parser.add_argument('--keys', type=Path, required=True)
parser.add_argument('--device-address', required=True)
args = parser.parse_args()
if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', args.device_address):
    parser.error('Expected a six-byte Bluetooth MAC address')
public = base64.b64decode(json.loads(args.keys.read_text())['advertisement_key'], validate=True)
if len(public) != 28:
    parser.error('Expected a 28-byte P-224 advertisement key')
address = bytes([public[0] | 0xc0]) + public[1:6]
payload = bytes.fromhex('1eff4c00121900') + public[6:] + bytes([public[0] >> 6, 0])
def lua_bytes(value):
    return 'string.char(' + ','.join(str(x) for x in value) + ')'
replacements = {
    '__PUBLIC_PAYLOAD__': lua_bytes(payload),
    '__PUBLIC_RANDOM_ADDRESS__': lua_bytes(address),
    '__DEVICE_ADDRESS_BYTES__': lua_bytes(bytes.fromhex(args.device_address.replace(':', ''))),
    '__PUBLIC_ADDRESS_TEXT__': json.dumps(':'.join(f'{x:02X}' for x in address)),
}
root = Path(__file__).resolve().parent
source = (root / 'main.lua.in').read_text()
for token, value in replacements.items():
    source = source.replace(token, value)
(root / 'main.lua').write_text(source)
print('Personalized Lua generated. Private key was not embedded.')
