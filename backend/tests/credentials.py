"""Build browser-equivalent encrypted credential requests for API tests."""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypted_body(client, path, body):
    response = client.get("/api/auth/public-key")
    assert response.status_code == 200
    public_key = serialization.load_der_public_key(base64.b64decode(response.json()["key"]))
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    data = AESGCM(aes_key).encrypt(iv, json.dumps(body).encode(), path.removeprefix("/api").encode())
    wrapped_key = public_key.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return {name: base64.b64encode(value).decode() for name, value in (("key", wrapped_key), ("iv", iv), ("data", data))}


def credential_post(client, path, body):
    return client.post(path, json=encrypted_body(client, path, body))
