import hmac
import hashlib
import time
from django.conf import settings
from django.core.cache import cache

class CryptographicQRService:
    """
    Wave 7: Cryptographic QR Security & Binding.
    Provides HMAC-SHA256 signed QR tokens with strict TTL and replay defense.
    """
    
    # In production, use settings.SECRET_KEY or a dedicated rotating secret
    QR_SECRET = b"hr-enterprise-qr-secret-key-2026"
    TTL_SECONDS = 30
    
    @classmethod
    def generate_signed_token(cls, site_id: int) -> str:
        """
        Generates a cryptographic token containing the site_id and current timestamp.
        Format: site_id|timestamp|hmac_signature
        """
        timestamp = int(time.time())
        payload = f"{site_id}|{timestamp}".encode('utf-8')
        
        signature = hmac.new(cls.QR_SECRET, payload, hashlib.sha256).hexdigest()
        return f"{site_id}|{timestamp}|{signature}"

    @classmethod
    def validate_token(cls, token: str, site_id: int) -> tuple[bool, str]:
        """
        Validates the signature, TTL, and ensures it hasn't been replayed across the entire system.
        """
        parts = token.split('|')
        if len(parts) != 3:
            return False, "Invalid QR Token format."
            
        token_site, token_timestamp_str, provided_signature = parts
        
        # 1. Validate Site
        if str(site_id) != token_site:
            return False, "QR Token does not belong to this site."
            
        # 2. Validate HMAC Signature (Cryptographic integrity)
        payload = f"{token_site}|{token_timestamp_str}".encode('utf-8')
        expected_signature = hmac.new(cls.QR_SECRET, payload, hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(expected_signature, provided_signature):
            return False, "QR Token signature forgery detected."
            
        # 3. Validate TTL (Strict 30 seconds)
        try:
            token_timestamp = int(token_timestamp_str)
        except ValueError:
            return False, "Invalid QR Token timestamp."
            
        current_time = int(time.time())
        if current_time - token_timestamp > cls.TTL_SECONDS:
            return False, f"QR Token expired. Strict {cls.TTL_SECONDS}s TTL enforced."
            
        # 4. Global Replay Defense (Consumed Tokens Cache)
        # We store the unique signature in Redis for the duration of its TTL.
        # If it's already in the cache, multiple people are trying to use the exact same QR snapshot.
        cache_key = f"qr_consumed_{provided_signature}"
        if cache.get(cache_key):
            return False, "QR Token Replay Attack: This specific token was already consumed."
            
        # Mark as consumed globally
        cache.set(cache_key, True, timeout=cls.TTL_SECONDS)
        
        return True, "Valid"
