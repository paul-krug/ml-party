"""Identity substrate: users, roles, per-user API tokens, sessions.

Server-side config, never knowledge — lives in `<root>/auth/`, not the
journal. Designed SSO-proof (DESIGN.md §12): users are keyed by an internal
ULID and carry an `identities` list, credential verification is one
pluggable step (`verify_password` today, an OIDC callback later — Entra ID
is the first planned provider), and sessions/tokens/roles are shared by
every authenticator. The password hash is just one optional identity.

Auth is OFF until the first user exists (`mlp user add`); a store without
users behaves exactly as if this module did not exist.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from .ids import new_id

ROLES = ("viewer", "writer", "admin")
_RANK = {r: i for i, r in enumerate(ROLES)}

SESSION_TTL_SECONDS = 14 * 24 * 3600
BOARD_TOKEN_TTL_SECONDS = 12 * 3600

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    pass


def role_at_least(role: str, minimum: str) -> bool:
    return _RANK.get(role, -1) >= _RANK[minimum]


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt,
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=64)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, n, r, p, salt_b64, dk_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64),
                            n=int(n), r=int(r), p=int(p), dklen=64)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class AuthStore:
    """Users + tokens in `<root>/auth/users.json` (small, text, diffable,
    backed up with the store); sessions are stateless HMAC-signed cookies
    (secret at `<root>/auth/secret`) so a restart logs nobody out."""

    def __init__(self, root: Path | str):
        self.dir = Path(root) / "auth"
        self.users_path = self.dir / "users.json"
        self._secret: bytes | None = None

    # ------------------------------------------------------------------ state

    @property
    def enabled(self) -> bool:
        return self.users_path.exists() and bool(self._load()["users"])

    def _load(self) -> dict:
        if not self.users_path.exists():
            return {"users": []}
        return json.loads(self.users_path.read_text())

    def _save(self, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.users_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        tmp.rename(self.users_path)

    def secret(self) -> bytes:
        if self._secret is None:
            path = self.dir / "secret"
            if not path.exists():
                self.dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(secrets.token_bytes(32))
                path.chmod(0o600)
            self._secret = path.read_bytes()
        return self._secret

    # ------------------------------------------------------------------ users

    def user_add(self, username: str, password: str | None, role: str = "writer",
                 email: str | None = None) -> dict:
        username = username.strip().lower()
        if not username:
            raise AuthError("username required")
        if role not in ROLES:
            raise AuthError(f"role must be one of {ROLES}")
        data = self._load()
        if any(u["username"] == username for u in data["users"]):
            raise AuthError(f"user {username!r} already exists")
        if not data["users"] and role != "admin":
            raise AuthError("the first user must be an admin (it bootstraps the store)")
        user = {
            "id": new_id(), "username": username, "email": email, "role": role,
            "password_hash": hash_password(password) if password else None,
            "identities": [{"provider": "password"}] if password else [],
            "tokens": [],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        data["users"].append(user)
        self._save(data)
        return {k: v for k, v in user.items() if k != "password_hash"}

    def user_list(self) -> list[dict]:
        return [
            {"id": u["id"], "username": u["username"], "email": u.get("email"),
             "role": u["role"], "tokens": [
                 {"id": t["id"], "name": t["name"], "created_at": t["created_at"]}
                 for t in u.get("tokens", [])],
             "identities": [i["provider"] for i in u.get("identities", [])]}
            for u in self._load()["users"]
        ]

    def user_get(self, ref: str) -> dict | None:
        """By id or username."""
        ref_l = ref.strip().lower()
        for u in self._load()["users"]:
            if u["id"] == ref or u["username"] == ref_l:
                return u
        return None

    def user_remove(self, ref: str) -> None:
        data = self._load()
        target = next((u for u in data["users"]
                       if u["id"] == ref or u["username"] == ref.strip().lower()), None)
        if target is None:
            raise AuthError(f"no user {ref!r}")
        admins = [u for u in data["users"] if u["role"] == "admin"]
        if target["role"] == "admin" and len(admins) == 1:
            raise AuthError("refusing to remove the last admin")
        data["users"].remove(target)
        self._save(data)

    def user_set_role(self, ref: str, role: str) -> dict:
        if role not in ROLES:
            raise AuthError(f"role must be one of {ROLES}")
        data = self._load()
        target = next((u for u in data["users"]
                       if u["id"] == ref or u["username"] == ref.strip().lower()), None)
        if target is None:
            raise AuthError(f"no user {ref!r}")
        if (target["role"] == "admin" and role != "admin"
                and sum(1 for u in data["users"] if u["role"] == "admin") == 1):
            raise AuthError("refusing to demote the last admin")
        target["role"] = role
        self._save(data)
        return {"username": target["username"], "role": role}

    def user_set_password(self, ref: str, password: str) -> None:
        data = self._load()
        target = next((u for u in data["users"]
                       if u["id"] == ref or u["username"] == ref.strip().lower()), None)
        if target is None:
            raise AuthError(f"no user {ref!r}")
        target["password_hash"] = hash_password(password)
        if not any(i["provider"] == "password" for i in target.setdefault("identities", [])):
            target["identities"].append({"provider": "password"})
        self._save(data)

    def authenticate_password(self, username: str, password: str) -> dict | None:
        """The password authenticator — one pluggable credential check.
        An OIDC callback is a sibling of this function, never a rework."""
        user = self.user_get(username)
        if user is None:
            verify_password(password, None)  # constant-ish time on unknown user
            return None
        return user if verify_password(password, user.get("password_hash")) else None

    # ----------------------------------------------------------------- tokens

    def token_create(self, user_ref: str, name: str) -> dict:
        """Returns the secret ONCE; only its sha256 is stored."""
        data = self._load()
        user = next((u for u in data["users"]
                     if u["id"] == user_ref or u["username"] == user_ref.strip().lower()),
                    None)
        if user is None:
            raise AuthError(f"no user {user_ref!r}")
        token_id = new_id()
        secret_part = secrets.token_urlsafe(32)
        token = f"mlp_{token_id}_{secret_part}"
        user.setdefault("tokens", []).append({
            "id": token_id, "name": name,
            "sha256": hashlib.sha256(token.encode()).hexdigest(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        self._save(data)
        return {"token": token, "id": token_id, "user": user["username"]}

    def token_revoke(self, token_id: str) -> None:
        data = self._load()
        for u in data["users"]:
            tokens = u.get("tokens", [])
            hit = next((t for t in tokens if t["id"] == token_id), None)
            if hit:
                tokens.remove(hit)
                self._save(data)
                return
        raise AuthError(f"no token {token_id!r}")

    def authenticate_token(self, token: str) -> dict | None:
        if not token.startswith("mlp_"):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        for u in self._load()["users"]:
            for t in u.get("tokens", []):
                if hmac.compare_digest(t["sha256"], digest):
                    return u
        return None

    # --------------------------------------------------------------- sessions

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.secret(), payload, hashlib.sha256).hexdigest()

    def _pw_fingerprint(self, user: dict) -> str:
        return hashlib.sha256((user.get("password_hash") or "").encode()).hexdigest()[:16]

    def issue_session(self, user: dict, ttl: int = SESSION_TTL_SECONDS) -> str:
        payload = _b64url(json.dumps({
            "uid": user["id"], "exp": int(time.time()) + ttl,
            "pwf": self._pw_fingerprint(user),  # password reset ends sessions
        }).encode())
        return f"{payload}.{self._sign(payload.encode())}"

    def verify_session(self, value: str | None) -> dict | None:
        claims = self._verify_signed(value, require_keys=("uid", "pwf"))
        if claims is None:
            return None
        user = self.user_get(claims["uid"])
        if user is None or claims["pwf"] != self._pw_fingerprint(user):
            return None
        return user

    def issue_read_token(self, ttl: int = BOARD_TOKEN_TTL_SECONDS) -> str:
        """Short-lived read-only bearer for sandboxed boards (opaque origins
        carry no cookies); accepted only where reads are served."""
        payload = _b64url(json.dumps(
            {"scope": "read", "exp": int(time.time()) + ttl}).encode())
        return f"{payload}.{self._sign(payload.encode())}"

    def verify_read_token(self, value: str | None) -> bool:
        return self._verify_signed(value, require_keys=("scope",)) is not None

    def _verify_signed(self, value: str | None,
                       require_keys: tuple[str, ...]) -> dict[str, Any] | None:
        if not value or "." not in value:
            return None
        payload, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(payload.encode()), sig):
            return None
        try:
            claims = json.loads(_unb64url(payload))
        except (ValueError, TypeError):
            return None
        if claims.get("exp", 0) < time.time():
            return None
        if any(k not in claims for k in require_keys):
            return None
        return claims
