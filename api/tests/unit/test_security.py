import unittest
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.security import (
    JWT_ALGORITHM,
    SecretNotConfiguredError,
    TokenError,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

SECRET = "a-secret-that-is-long-enough-for-hs256"
USER_ID = uuid.uuid4()


class TestPasswords(unittest.TestCase):
    def test_hash_verifies_and_is_salted(self):
        first, second = hash_password("s3cret-passphrase"), hash_password("s3cret-passphrase")

        self.assertNotEqual(first, second)
        self.assertNotIn("s3cret", first)
        self.assertTrue(verify_password("s3cret-passphrase", first))
        self.assertFalse(verify_password("wrong", first))

    def test_unknown_user_hash_never_verifies(self):
        self.assertFalse(verify_password("anything", None))
        self.assertFalse(verify_password("not-a-real-password", None))

    def test_malformed_hash_is_a_failed_verification(self):
        self.assertFalse(verify_password("x", "not-an-argon2-hash"))


class TestTokens(unittest.TestCase):
    def make(self, kind=TokenType.ACCESS, ttl=timedelta(minutes=1), secret=SECRET):
        return create_token(USER_ID, kind, ttl, secret)

    def test_roundtrip(self):
        self.assertEqual(decode_token(self.make(), TokenType.ACCESS, SECRET), USER_ID)

    def test_expired_token_is_rejected(self):
        with self.assertRaises(TokenError):
            decode_token(self.make(ttl=timedelta(seconds=-1)), TokenType.ACCESS, SECRET)

    def test_tampered_token_is_rejected(self):
        header, payload, signature = self.make().split(".")
        forged = jwt.encode(
            {"sub": str(uuid.uuid4()), "type": "access", "exp": datetime.now(UTC) + timedelta(1)},
            "another-secret-of-enough-length-for-hs256",
            algorithm=JWT_ALGORITHM,
        )
        for token in (f"{header}.{payload}.{signature[:-2]}xx", forged, "garbage", ""):
            with self.subTest(token=token[:20]), self.assertRaises(TokenError):
                decode_token(token, TokenType.ACCESS, SECRET)

    def test_token_type_is_enforced_both_ways(self):
        with self.assertRaises(TokenError):
            decode_token(self.make(TokenType.REFRESH), TokenType.ACCESS, SECRET)
        with self.assertRaises(TokenError):
            decode_token(self.make(TokenType.ACCESS), TokenType.REFRESH, SECRET)

    def test_unsigned_and_claimless_tokens_are_rejected(self):
        unsigned = jwt.encode({"sub": str(USER_ID)}, "", algorithm="none")
        no_exp = jwt.encode({"sub": str(USER_ID), "type": "access"}, SECRET, algorithm="HS256")
        bad_sub = jwt.encode(
            {"sub": "not-a-uuid", "type": "access", "exp": datetime.now(UTC) + timedelta(1)},
            SECRET,
            algorithm="HS256",
        )
        for token in (unsigned, no_exp, bad_sub):
            with self.assertRaises(TokenError):
                decode_token(token, TokenType.ACCESS, SECRET)

    def test_short_or_empty_secret_is_refused(self):
        for secret in ("", "short"):
            with self.assertRaises(SecretNotConfiguredError):
                create_token(USER_ID, TokenType.ACCESS, timedelta(1), secret)
            with self.assertRaises(SecretNotConfiguredError):
                decode_token("x", TokenType.ACCESS, secret)


if __name__ == "__main__":
    unittest.main()
