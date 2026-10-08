"""Password hashing and short-lived signed local API sessions."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from .db import ROOT


def hash_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError('密码长度必须为 8—128 个字符')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return 'pbkdf2_sha256$600000$' + salt.hex() + '$' + digest.hex()


def verify_password(password, encoded):
    try:
        alg, iterations, salt, digest = encoded.split('$')
        if alg != 'pbkdf2_sha256' or not isinstance(password, str) or len(password) > 128:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


def signing_key():
    if os.environ.get('VOLUNTEER_TOKEN_SECRET'):
        return os.environ['VOLUNTEER_TOKEN_SECRET'].encode()
    path = ROOT / '.work/token-secret'
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open('xb') as f:
            f.write(secrets.token_bytes(48))
    except FileExistsError:
        pass
    return path.read_bytes()


def issue_token(actor):
    payload = json.dumps({'kind': actor['kind'], 'id':str(actor['id']),
                          'exp':int(time.time())+3600}, separators=(',',':')).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b'=')
    signature = hmac.new(signing_key(), body, hashlib.sha256).hexdigest()
    return body.decode() + '.' + signature


def read_token(token):
    try:
        if len(token) > 2048:
            raise ValueError()
        body, signature = token.split('.')
        expected = hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + '='*(-len(body)%4)))
        if data['exp'] <= time.time() or data['kind'] not in ('student','admin'):
            raise ValueError()
        return {'kind':data['kind'], 'id':data['id']}
    except (ValueError, KeyError, TypeError):
        raise ValueError('登录已过期或令牌无效') from None
