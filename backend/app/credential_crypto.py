"""Encrypt credential request bodies with a per-request AES key wrapped by RSA-OAEP."""

import base64
import json

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class EncryptedCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=512)
    iv: str = Field(max_length=32)
    data: str = Field(max_length=4096)


def public_key() -> str:
    der = _private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def decrypt_credentials(encrypted: EncryptedCredentials, path: str, schema: type[BaseModel]):
    try:
        wrapped_key = base64.b64decode(encrypted.key, validate=True)
        iv = base64.b64decode(encrypted.iv, validate=True)
        data = base64.b64decode(encrypted.data, validate=True)
        if len(iv) != 12 or len(data) > 3072:
            raise ValueError("Invalid encrypted credentials")
        key = _private_key.decrypt(
            wrapped_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        if len(key) != 32:
            raise ValueError("Invalid AES key")
        plaintext = AESGCM(key).decrypt(iv, data, path.encode("utf-8"))
        return schema.model_validate(json.loads(plaintext))
    except (ValueError, TypeError, KeyError, InvalidTag, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(422, "加密凭据无效，请重试") from None
