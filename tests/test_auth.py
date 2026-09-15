import pytest

from mlparty.auth import AuthError, AuthStore, hash_password, verify_password


@pytest.fixture
def auth(tmp_path):
    return AuthStore(tmp_path)


def test_password_roundtrip():
    enc = hash_password("hunter22")
    assert verify_password("hunter22", enc)
    assert not verify_password("hunter23", enc)
    assert not verify_password("hunter22", None)
    assert not verify_password("hunter22", "garbage")


def test_disabled_until_first_user(auth):
    assert not auth.enabled
    auth.user_add("paul", "pw123456", role="admin")
    assert auth.enabled


def test_first_user_must_be_admin(auth):
    with pytest.raises(AuthError, match="first user"):
        auth.user_add("paul", "pw123456", role="writer")


def test_user_lifecycle(auth):
    auth.user_add("paul", "pw123456", role="admin")
    auth.user_add("kim", "pw234567", role="viewer")
    assert {u["username"] for u in auth.user_list()} == {"paul", "kim"}
    assert auth.authenticate_password("paul", "pw123456")["role"] == "admin"
    assert auth.authenticate_password("paul", "wrong") is None
    assert auth.authenticate_password("nobody", "pw123456") is None

    auth.user_set_role("kim", "writer")
    assert auth.user_get("kim")["role"] == "writer"
    with pytest.raises(AuthError, match="already exists"):
        auth.user_add("paul", "x2345678")
    with pytest.raises(AuthError, match="last admin"):
        auth.user_remove("paul")
    with pytest.raises(AuthError, match="last admin"):
        auth.user_set_role("paul", "viewer")
    auth.user_remove("kim")
    assert len(auth.user_list()) == 1
    # no password hashes in listings
    assert "password_hash" not in auth.user_list()[0]


def test_tokens(auth):
    auth.user_add("paul", "pw123456", role="admin")
    out = auth.token_create("paul", "laptop-sync")
    assert out["token"].startswith("mlp_")
    assert auth.authenticate_token(out["token"])["username"] == "paul"
    assert auth.authenticate_token("mlp_bogus_bogus") is None
    assert auth.authenticate_token("Bearer whatever") is None
    # stored hashed, revocable
    assert out["token"] not in auth.users_path.read_text()
    auth.token_revoke(out["id"])
    assert auth.authenticate_token(out["token"]) is None
    with pytest.raises(AuthError):
        auth.token_revoke(out["id"])


def test_sessions(auth):
    auth.user_add("paul", "pw123456", role="admin")
    user = auth.user_get("paul")
    cookie = auth.issue_session(user)
    assert auth.verify_session(cookie)["username"] == "paul"
    assert auth.verify_session(None) is None
    assert auth.verify_session("tampered." + cookie.split(".")[1]) is None
    # expired session rejected
    expired = auth.issue_session(user, ttl=-1)
    assert auth.verify_session(expired) is None
    # password reset invalidates existing sessions
    auth.user_set_password("paul", "newpw12345")
    assert auth.verify_session(cookie) is None
    assert auth.authenticate_password("paul", "newpw12345")


def test_read_token(auth):
    auth.user_add("paul", "pw123456", role="admin")
    bt = auth.issue_read_token()
    assert auth.verify_read_token(bt)
    assert not auth.verify_read_token(auth.issue_read_token(ttl=-1))
    assert not auth.verify_read_token("nope")
    # a read token is not a session and vice versa
    assert auth.verify_session(bt) is None
    assert not auth.verify_read_token(auth.issue_session(auth.user_get("paul")))
