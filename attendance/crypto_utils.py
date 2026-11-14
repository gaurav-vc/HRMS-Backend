import os
import json
import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet
from typing import Dict, Any

def _get_master_kek() -> bytes:
    """Derives or retrieves the Master Key Encryption Key (KEK) dynamically."""
    custom_kek = getattr(settings, 'HRMS_MASTER_KEK', None)
    if custom_kek:
        return custom_kek.encode('utf-8') if isinstance(custom_kek, str) else custom_kek
    secret = getattr(settings, 'SECRET_KEY', 'default-hrms-dev-secret-key-32b!')
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())

class AWSKMSMock:
    """
    KMS Envelope Encryption implementation.
    Uses master KEK derived from environment/settings for DEK encryption.
    """
    @classmethod
    def generate_data_key(cls) -> tuple[bytes, bytes]:
        """
        Generates a new Data Encryption Key (DEK).
        Returns (Plaintext DEK, Encrypted DEK).
        """
        plaintext_dek = Fernet.generate_key()
        master_cipher = Fernet(_get_master_kek())
        encrypted_dek = master_cipher.encrypt(plaintext_dek)
        return plaintext_dek, encrypted_dek
        
    @classmethod
    def decrypt_data_key(cls, encrypted_dek: bytes) -> bytes:
        """
        Decrypts the DEK using the master KEK.
        """
        master_cipher = Fernet(_get_master_kek())
        return master_cipher.decrypt(encrypted_dek)

class CryptoService:
    """
    Application-Level Envelope Encryption Service.
    """
    @staticmethod
    def encrypt_json(payload: Dict[str, Any]) -> tuple[bytes, bytes]:
        """
        Encrypts a Python dictionary.
        Returns (Encrypted JSON Payload, Encrypted DEK).
        """
        plaintext_dek, encrypted_dek = AWSKMSMock.generate_data_key()
        f = Fernet(plaintext_dek)
        
        json_bytes = json.dumps(payload).encode('utf-8')
        encrypted_payload = f.encrypt(json_bytes)
        
        return encrypted_payload, encrypted_dek

    @staticmethod
    def decrypt_json(encrypted_payload: bytes, encrypted_dek: bytes) -> Dict[str, Any]:
        """
        Decrypts the payload using the provided encrypted DEK.
        """
        plaintext_dek = AWSKMSMock.decrypt_data_key(encrypted_dek)
        f = Fernet(plaintext_dek)
        
        json_bytes = f.decrypt(encrypted_payload)
        return json.loads(json_bytes.decode('utf-8'))
