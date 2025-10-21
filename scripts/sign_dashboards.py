"""Dashboard signing utility.

Provides detached signature for a dashboard archive using one of:
  * Ed25519 private key (base64) via env G6_SIGN_KEY (preferred)
  * Fallback HMAC-SHA256 with secret env G6_SIGN_SECRET (lower security)

Outputs signature file `<archive>.sig` and JSON summary (stdout) unless
--verify is used (then validates provided signature file).

Usage:
  python scripts/sign_dashboards.py --archive dist/dashboards_1.2.3.tar.gz
  python scripts/sign_dashboards.py --archive dist/dashboards_1.2.3.tar.gz --verify
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any

try:  # optional dependency
  from nacl import signing  # type: ignore
  HAVE_NACL = True
except Exception:  # pragma: no cover
  HAVE_NACL = False


def read_bytes(path: Path) -> bytes:
  return path.read_bytes()


def sign_ed25519(priv_b64: str, data: bytes) -> dict[str, Any]:
  if not HAVE_NACL:
    raise RuntimeError('PyNaCl not available')
  key_raw = base64.b64decode(priv_b64)
  signer = signing.SigningKey(key_raw)  # type: ignore[name-defined]
  sig = signer.sign(data).signature
  return {
    'algorithm': 'ed25519',
    'signature_b64': base64.b64encode(sig).decode('ascii'),
    'public_key_b64': base64.b64encode(signer.verify_key.encode()).decode('ascii'),
  }


def sign_hmac(secret: str, data: bytes) -> dict[str, Any]:
  mac = hmac.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
  return {
    'algorithm': 'hmac-sha256',
    'signature_b64': base64.b64encode(mac).decode('ascii'),
  }


def verify_ed25519(pub_b64: str, data: bytes, sig_b64: str) -> bool:
  try:
    from nacl.signing import VerifyKey  # type: ignore
    vk = VerifyKey(base64.b64decode(pub_b64))
    sig = base64.b64decode(sig_b64)
    vk.verify(data, sig)
    return True
  except Exception:
    return False


def verify_hmac(secret: str, data: bytes, sig_b64: str) -> bool:
  mac = hmac.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
  return hmac.compare_digest(mac, base64.b64decode(sig_b64))


def parse_args() -> argparse.Namespace:
  ap = argparse.ArgumentParser(description='Dashboard archive signing tool')
  ap.add_argument('--archive', required=True, help='Dashboard archive path (tar.gz)')
  ap.add_argument('--verify', action='store_true', help='Verify instead of sign')
  ap.add_argument('--signature', help='Signature file (defaults to <archive>.sig)')
  ap.add_argument('--public-key', help='Public key base64 (verify mode Ed25519)')
  ap.add_argument('--algorithm', choices=['auto','ed25519','hmac'], default='auto')
  ap.add_argument('--output-json', action='store_true', help='Emit JSON summary (default true when signing)')
  return ap.parse_args()


def choose_algorithm(args: argparse.Namespace) -> str:
  algo = str(args.algorithm)
  if algo != 'auto':
    return algo
  if os.getenv('G6_SIGN_KEY') and HAVE_NACL:
    return 'ed25519'
  if os.getenv('G6_SIGN_SECRET'):
    return 'hmac'
  return 'hmac'  # final fallback (will fail if secret absent)


def main() -> int:  # pragma: no cover
  args = parse_args()
  arc = Path(args.archive)
  if not arc.exists():
    print(f"Archive missing: {arc}", file=sys.stderr)
    return 2
  sig_path = Path(args.signature) if args.signature else Path(str(arc) + '.sig')
  algo = choose_algorithm(args)
  data = read_bytes(arc)

  if args.verify:
    if not sig_path.exists():
      print(f"Signature file missing: {sig_path}", file=sys.stderr)
      return 3
    sig_b64 = sig_path.read_text(encoding='utf-8').strip()
    ok = False
    if algo == 'ed25519':
      pub = args.public_key or os.getenv('G6_SIGN_PUB')
      if not pub:
        print('Public key required for Ed25519 verify', file=sys.stderr)
        return 4
      ok = verify_ed25519(pub, data, sig_b64)
    else:
      secret = os.getenv('G6_SIGN_SECRET')
      if not secret:
        print('G6_SIGN_SECRET not set for HMAC verify', file=sys.stderr)
        return 5
      ok = verify_hmac(secret, data, sig_b64)
    print(json.dumps({'verify': ok, 'algorithm': algo, 'archive': str(arc)}))
    return 0 if ok else 6

  # Signing mode
  if algo == 'ed25519':
    if not HAVE_NACL:
      print('PyNaCl not installed; cannot use Ed25519', file=sys.stderr)
      return 7
    priv = os.getenv('G6_SIGN_KEY')
    if not priv:
      print('G6_SIGN_KEY not set', file=sys.stderr)
      return 8
    meta = sign_ed25519(priv, data)
  else:
    secret = os.getenv('G6_SIGN_SECRET')
    if not secret:
      print('G6_SIGN_SECRET not set for HMAC signing', file=sys.stderr)
      return 9
    meta = sign_hmac(secret, data)

  sig_path.write_text(meta['signature_b64'] + '\n', encoding='utf-8')
  meta_out = {
    'archive': str(arc),
    'signature_file': str(sig_path),
    **meta,
  }
  if args.output_json or True:
    print(json.dumps(meta_out, indent=2))
  return 0

if __name__ == '__main__':  # pragma: no cover
  raise SystemExit(main())
