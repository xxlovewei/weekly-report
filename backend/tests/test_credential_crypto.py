import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.credential_crypto import EncryptedCredentials, decrypt_credentials, public_key
from tests.credentials import encrypted_body


class Credentials(BaseModel):
    password: str


class KeyClient:
    def get(self, _path):
        class Response:
            status_code = 200

            def json(self):
                return {"key": public_key()}

        return Response()


def test_encrypted_credentials_bind_payload_to_endpoint():
    body = encrypted_body(KeyClient(), "/api/auth/login", {"password": "秘密密码"})
    encrypted = EncryptedCredentials.model_validate(body)
    assert "秘密密码" not in str(body)
    assert decrypt_credentials(encrypted, "/auth/login", Credentials).password == "秘密密码"
    with pytest.raises(HTTPException) as wrong_endpoint:
        decrypt_credentials(encrypted, "/auth/password", Credentials)
    assert wrong_endpoint.value.status_code == 422
    with pytest.raises(HTTPException) as damaged_data:
        decrypt_credentials(EncryptedCredentials.model_validate({**body, "data": "AAAA"}), "/auth/login", Credentials)
    assert damaged_data.value.status_code == 422
