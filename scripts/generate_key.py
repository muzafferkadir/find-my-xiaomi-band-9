#!/usr/bin/env python3
"""Generate a private P-224 beacon identity outside the source tree."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = args.out.expanduser().resolve()
if output.is_relative_to(root):
    parser.error('Keep private keys outside the project directory')
key = ec.generate_private_key(ec.SECP224R1()).private_numbers()
public = key.public_numbers.x.to_bytes(28, 'big')
def b64(value):
    return base64.b64encode(value).decode()
data = {
    'name': 'Band 9', 'created_at': datetime.now(timezone.utc).isoformat(),
    'curve': 'secp224r1', 'private_key': b64(key.private_value.to_bytes(28, 'big')),
    'advertisement_key': b64(public),
    'hashed_advertisement_key': b64(hashlib.sha256(public).digest()),
}
with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
    json.dump(data, file, indent=2)
    file.write('\n')
print('Private identity created with mode 0600. Back up this file privately.')
