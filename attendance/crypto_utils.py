import os
import json
import base64
from cryptography.fernet import Fernet
from typing import Dict, Any

class AWSKMSMock:
    """
    Mock implementation of AWS Key Management Service (KMS).
    In production, this would use boto3.client('kms').
    """
    _MASTER_KEK = b'r3v8j1nK_QvX9wzG7L4P2tM5c8H1kF4=' # Mock Key Encryption Key
    
    @classmethod
    def generate_data_key(cls) -> tuple[bytes, bytes]:
        """
        Generates a new Data Encryption Key (DEK).
        Returns (Plaintext DEK, Encrypted DEK).
        """
        plaintext_dek = Fernet.generate_key()
        # In reality, KMS encrypts the DEK. We mock it by XOR or just returning base64.
        # For this prototype, we'll just base64 encode it as the "encrypted" version.
        encrypted_dek = base64.b64encode(plaintext_dek)
        return plaintext_dek, encrypted_dek
        
    @classmethod
    def decrypt_data_key(cls, encrypted_dek: bytes) -> bytes:
        """
        Decrypts the DEK using the master KEK.
        """
        # Mock decryption
        return base64.b64decode(encrypted_dek)

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
