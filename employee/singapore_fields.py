"""Encryption for HR identifiers; keys follow Django's secret-key rotation."""

import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import models


def identifier_cipher():
    # Domain separation prevents reuse of Django's signing key as a Fernet key.
    keys = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    return MultiFernet([
        Fernet(base64.urlsafe_b64encode(hashlib.sha256(
            ("horilla:sg-hr-identifiers:v1:" + key).encode()
        ).digest())) for key in keys
    ])


class EncryptedHRTextField(models.TextField):
    """Plaintext in validated models/forms, ciphertext in the database."""

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return identifier_cipher().decrypt(value.encode()).decode()

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return identifier_cipher().encrypt(value.encode()).decode() if value else value
