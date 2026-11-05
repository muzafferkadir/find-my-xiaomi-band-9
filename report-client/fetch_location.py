#!/usr/bin/env python3
"""Fetch reports for the user's generated Band9 key with local interactive login."""
import argparse
import asyncio
import base64
import getpass
import json
import logging
import os
from pathlib import Path
import re

from findmy import KeyPair, LoginState
from native_anisette import NativeAnisetteProvider, _AkdHttpSession, _native_async_account_cls
from findmy.errors import InvalidCredentialsError
from findmy import SmsSecondFactorMethod, TrustedDeviceSecondFactorMethod

KEY_PATH = Path.home() / 'Downloads/band9-findmy-keys.json'
STATE_DIR = Path.home() / 'Library/Application Support/Band9FindMy'


class DiagnosticAccount(_native_async_account_cls()):
    async def _gsa_request(self, parameters):
        response = await super()._gsa_request(parameters)
        status = response.get('Status', {})
        if status.get('ec', 0) != 0:
            stage = parameters.get('o')
            if stage in {'init', 'complete'}:
                code = status.get('ec')
                safe_code = str(code) if re.fullmatch(r'-?\d+', str(code)) else 'unknown'
                print(f'Apple auth stage: {stage}; error code: {safe_code}')
        return response


async def make_account(state_info=None):
    account = DiagnosticAccount(NativeAnisetteProvider(), state_info=state_info)
    await account._http.close()
    account._http = _AkdHttpSession()
    return account


def save_account(account, path):
    data = account.to_json()
    data['account']['password'] = None
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)


def credential_error_message(error):
    message = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[email]', str(error))
    message = message.replace('\r', ' ').replace('\n', ' ')[:300]
    if message.startswith('Email verification failed:'):
        stage = 'Apple rejected at the email/client stage, before password verification.'
    elif message.startswith('Password authentication failed:'):
        stage = 'Apple rejected at the password verification stage.'
    else:
        stage = 'Apple rejected the login request; stage could not be determined.'
    return stage + '\nApple response: ' + message


def load_key(path):
    data = json.loads(path.expanduser().read_text())
    key = KeyPair.from_b64(data['private_key'])
    if key.adv_key_bytes != base64.b64decode(data['advertisement_key']):
        raise ValueError('Private and advertisement keys differ')
    return key


async def authenticate(account):
    email = input('Apple account email: ').strip()
    password = getpass.getpass('Apple password (hidden): ')
    state = await account.login(email, password)
    del password
    if state == LoginState.REQUIRE_2FA:
        methods = await account.get_2fa_methods()
        for index, method in enumerate(methods, 1):
            if isinstance(method, TrustedDeviceSecondFactorMethod):
                label = 'Trusted Apple device'
            elif isinstance(method, SmsSecondFactorMethod):
                label = 'SMS: ' + method.phone_number
            else:
                label = type(method).__name__
            print(f'[{index}] {label}')
        selected = int(input('Verification method number: ')) - 1
        if not 0 <= selected < len(methods):
            raise ValueError('Invalid verification method')
        method = methods[selected]
        await method.request()
        await method.submit(input('Apple verification code: ').strip())


async def main():
    parser = argparse.ArgumentParser(description='Band 9 Find My location report check')
    parser.add_argument('--self-check', action='store_true', help='Verify the key without contacting Apple')
    parser.add_argument('--login', action='store_true', help='Log in again instead of reusing the saved session')
    parser.add_argument('--keys', type=Path, default=KEY_PATH, help='Private beacon identity JSON')
    parser.add_argument('--export', type=Path, help='Save a location-only JSON')
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.CRITICAL)
    key = load_key(args.keys)
    if args.self_check:
        print('Key pair verified. No connection to Apple was made.')
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_DIR, 0o700)
    session_path = STATE_DIR / 'account.json'
    account = None
    try:
        state_info = None
        if session_path.exists() and not args.login:
            stored = json.loads(session_path.read_text())
            if stored.get('anisette', {}).get('type') == 'aniNative':
                state_info = stored
        account = await make_account(state_info)
        print('Login identity: this Mac\'s native AOSKit/AuthKit identity.')
        if state_info is None:
            await authenticate(account)
        save_account(account, session_path)
        print('Requesting the latest location report for Band 9...')
        location = await account.fetch_location(key)
        save_account(account, session_path)
        if location is None:
            print('No location report for this key yet. Run again later while the band is advertising.')
            return 1
        result = {
            'timestamp': location.timestamp.isoformat(),
            'latitude': location.latitude,
            'longitude': location.longitude,
            'horizontal_accuracy': location.horizontal_accuracy,
            'confidence': location.confidence,
        }
        report_path = STATE_DIR / 'last-location.json'
        report_path.write_text(json.dumps(result, indent=2) + '\n')
        os.chmod(report_path, 0o600)
        if args.export:
            export = args.export.expanduser().resolve()
            if export == args.keys.expanduser().resolve() or export == session_path.resolve():
                raise ValueError('Export must not overwrite credentials')
            export.write_text(json.dumps(result, indent=2) + '\n')
            os.chmod(export, 0o600)
        print('Report fetched from Apple\'s network and decrypted with your own key.')
        print('Time: ' + result['timestamp'])
        print(f"Location: {result['latitude']}, {result['longitude']}")
        print(f"Map: https://maps.google.com/?q={result['latitude']},{result['longitude']}")
        return 0
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 130
    except InvalidCredentialsError as error:
        print(credential_error_message(error))
        print('This output contains no password or token; safe to share for diagnosis.')
        return 2
    except Exception as error:
        status = re.search(r'(?:HTTP|status|response[^:]*:)\s*(\d{3})', str(error), re.IGNORECASE)
        detail = f' (HTTP {status.group(1)})' if status else ''
        print('Login or report request failed: ' + type(error).__name__ + detail)
        print('Re-run this command with --login to log in again.')
        return 2
    finally:
        if account is not None:
            await account.close()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
