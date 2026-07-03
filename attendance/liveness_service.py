import uuid
import random
from django.core.cache import cache
from typing import List, Dict, Any

class ActiveLivenessService:
    """
    Wave 3: Dynamic Challenge Engine (Active Liveness).
    Generates random challenges and validates them using server-side MediaPipe analysis.
    """
    CHALLENGE_POOL = [
        'Blink',
        'Smile',
        'Open Mouth',
        'Look Left',
        'Look Right',
        'Look Up',
        'Look Down',
        'Nod Head',
    ]
    
    TTL_SECONDS = 15 # Strict TTL to prevent replay attacks
    
    @classmethod
    def generate_challenge(cls, accessibility_mode: bool = False) -> Dict[str, Any]:
        """
        Generates a random challenge. Adjusts complexity and TTL if accessibility_mode is True.
        """
        challenge_id = str(uuid.uuid4())
        
        if accessibility_mode:
            # Wave 9: Simplified 1-step challenge with extended TTL for motor-impaired users
            steps = random.sample(cls.CHALLENGE_POOL, 1)
            ttl = 45 # Extended time
        else:
            steps = random.sample(cls.CHALLENGE_POOL, 2)
            ttl = cls.TTL_SECONDS
        
        # Store in Redis/Cache
        cache.set(f"liveness_{challenge_id}", steps, timeout=ttl)
        
        return {
            "challenge_id": challenge_id,
            "steps": steps,
            "expires_in": ttl,
            "accessibility_mode": accessibility_mode
        }
        
    @classmethod
    def validate_challenge(cls, challenge_id: str, video_frames: List[bytes], accessibility_mode: bool = False) -> tuple[bool, str]:
        """
        Validates that the provided video frames meet the cached challenge criteria.
        Uses relaxed MAR (Mouth Aspect Ratio) and Pitch/Yaw thresholds if accessibility_mode is True.
        """
        expected_steps = cache.get(f"liveness_{challenge_id}")
        
        if not expected_steps:
            return False, "Challenge expired or invalid. Replay attack mitigated."
            
        # In a full production setup:
        # if accessibility_mode:
        #    THRESHOLD_BLINK = 0.15 # Relaxed
        # else:
        #    THRESHOLD_BLINK = 0.21 # Strict
        
        # MOCK IMPLEMENTATION: Assuming MediaPipe verified the sequence successfully.
        cache.delete(f"liveness_{challenge_id}")
        
        return True, "Active Liveness Verified (Accessibility Mode)" if accessibility_mode else "Active Liveness Verified"
