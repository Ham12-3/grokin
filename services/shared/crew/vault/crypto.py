"""Vault encryption (docs/09-security.md).

Each item gets its own random 32-byte data key. The value is encrypted with AES-256-GCM
under that key; the data key is then wrapped (encrypted) by a key the database never
holds: AWS KMS when `VAULT_KMS_KEY_ID` is set, otherwise `VAULT_MASTER_KEY` (dev).

The user id and item name are bound into the encryption, so a row copied to another user
or renamed in the database does not decrypt.
"""

import base64
import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

from crew.config import Settings


class VaultError(Exception):
    """The Vault cannot be used, or an item cannot be read. The message is safe to show."""


class KeyWrapper(Protocol):
    name: str

    def wrap(self, data_key: bytes) -> bytes: ...

    def unwrap(self, wrapped: bytes) -> bytes: ...


class MasterKeyWrapper:
    """Dev: AES key wrap (RFC 3394) with `VAULT_MASTER_KEY` (32 random bytes, base64)."""

    name = "master"

    def __init__(self, master_key_b64: str) -> None:
        try:
            key = base64.b64decode(master_key_b64, validate=True)
        except ValueError as error:
            raise VaultError("VAULT_MASTER_KEY is not valid base64.") from error
        if len(key) != 32:
            raise VaultError("VAULT_MASTER_KEY must be 32 bytes, base64 encoded.")
        self._key = key

    def wrap(self, data_key: bytes) -> bytes:
        return aes_key_wrap(self._key, data_key)

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            return aes_key_unwrap(self._key, wrapped)
        except InvalidUnwrap as error:
            raise VaultError("This item was saved with a different master key.") from error


class KmsKeyWrapper:
    """Prod: the data key is wrapped by AWS KMS and never leaves it unwrapped at rest."""

    name = "kms"

    def __init__(self, key_id: str, client: Any = None) -> None:
        self._key_id = key_id
        if client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as error:
                raise VaultError(
                    "VAULT_KMS_KEY_ID is set but boto3 is not installed (install the `aws` extra)."
                ) from error
            client = boto3.client("kms")
        self._client = client

    def wrap(self, data_key: bytes) -> bytes:
        wrapped: bytes = self._client.encrypt(KeyId=self._key_id, Plaintext=data_key)[
            "CiphertextBlob"
        ]
        return wrapped

    def unwrap(self, wrapped: bytes) -> bytes:
        plain: bytes = self._client.decrypt(KeyId=self._key_id, CiphertextBlob=wrapped)["Plaintext"]
        return plain


def create_wrapper(settings: Settings) -> KeyWrapper:
    if settings.vault_kms_key_id:
        return KmsKeyWrapper(settings.vault_kms_key_id)
    if settings.vault_master_key:
        return MasterKeyWrapper(settings.vault_master_key)
    raise VaultError(
        "The Vault is not set up on this server (set VAULT_MASTER_KEY or VAULT_KMS_KEY_ID)."
    )


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    wrapped_data_key: bytes
    wrapped_by: str


def _bound(user_id: uuid.UUID, name: str) -> bytes:
    return f"crew-vault:{user_id}:{name}".encode()


def seal(wrapper: KeyWrapper, user_id: uuid.UUID, name: str, value: str) -> Sealed:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(nonce, value.encode(), _bound(user_id, name))
    return Sealed(ciphertext, nonce, wrapper.wrap(data_key), wrapper.name)


def unseal(wrapper: KeyWrapper, user_id: uuid.UUID, name: str, sealed: Sealed) -> str:
    """Decrypts in memory. Call only at the moment a tool needs the value."""
    if sealed.wrapped_by != wrapper.name:
        raise VaultError("This item was saved with a different key setup.")
    data_key = wrapper.unwrap(sealed.wrapped_data_key)
    try:
        plain = AESGCM(data_key).decrypt(sealed.nonce, sealed.ciphertext, _bound(user_id, name))
    except InvalidTag as error:
        raise VaultError("This item cannot be read.") from error
    return plain.decode()
