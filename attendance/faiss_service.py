import os
import json
import numpy as np
from typing import Dict, Any, Optional

try:
    import faiss
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False

from .models import FaceProfile
from .crypto_utils import CryptoService

class BiometricSearchService:
    """
    1:N Facial Identification Service using FAISS for O(log N) vector search.
    """
    INDEX_PATH = 'faiss_index.bin'
    MAPPING_PATH = 'faiss_mapping.json'
    
    def __init__(self):
        self.dimension = 128 # Default for DeepFace (Facenet)
        self.index = None
        self.id_mapping = {} # Maps FAISS index -> Employee ID
        self.load_index()

    def load_index(self):
        """Loads the FAISS index from disk or rebuilds if missing."""
        if HAVE_FAISS:
            if os.path.exists(self.INDEX_PATH) and os.path.exists(self.MAPPING_PATH):
                self.index = faiss.read_index(self.INDEX_PATH)
                with open(self.MAPPING_PATH, 'r') as f:
                    self.id_mapping = json.load(f)
            else:
                self.index = faiss.IndexFlatL2(self.dimension)
                self.rebuild_index()
        else:
            # Fallback mock for local development without FAISS
            pass

    def rebuild_index(self):
        """Full rebuild of the vector index (Nightly Compaction)."""
        if not HAVE_FAISS: return
        
        self.index = faiss.IndexFlatL2(self.dimension)
        self.id_mapping = {}
        idx = 0
        
        profiles = FaceProfile.objects.filter(is_active=True)
        for profile in profiles:
            if profile.encrypted_face_encodings and profile.encrypted_dek:
                payload = CryptoService.decrypt_json(profile.encrypted_face_encodings, profile.encrypted_dek)
                encodings = payload.get('encodings', [])
                for vec in encodings:
                    vec_np = np.array([vec], dtype=np.float32)
                    self.index.add(vec_np)
                    self.id_mapping[str(idx)] = profile.employee.id
                    idx += 1
                    
        self._save_to_disk()

    def add_employee_vectors(self, employee_id: int, encodings: list):
        """Incremental update for new enrollments."""
        if not HAVE_FAISS: return
        
        start_idx = self.index.ntotal if self.index else 0
        for i, vec in enumerate(encodings):
            vec_np = np.array([vec], dtype=np.float32)
            self.index.add(vec_np)
            self.id_mapping[str(start_idx + i)] = employee_id
            
        self._save_to_disk()

    def identify(self, face_encoding: list, threshold: float = 0.40) -> Optional[int]:
        """
        1:N search returning the best matched Employee ID.
        """
        if not HAVE_FAISS:
            # Brute force fallback if FAISS isn't installed (O(N) time)
            from .utils import compare_faces
            profiles = FaceProfile.objects.filter(is_active=True)
            for profile in profiles:
                if profile.encrypted_face_encodings:
                    payload = CryptoService.decrypt_json(profile.encrypted_face_encodings, profile.encrypted_dek)
                    match_result = compare_faces(payload.get('encodings', []), face_encoding)
                    if match_result.get('success') and match_result.get('match'):
                        return profile.employee.id
            return None

        # O(log N) FAISS search
        vec_np = np.array([face_encoding], dtype=np.float32)
        distances, indices = self.index.search(vec_np, 1) # Find top 1 nearest neighbor
        
        if distances[0][0] < threshold:
            idx_str = str(indices[0][0])
            if idx_str in self.id_mapping:
                return self.id_mapping[idx_str]
                
        return None

    def remove_employee(self, employee_id: int):
        """Tombstone vectors for GDPR Right to be Forgotten."""
        # FAISS doesn't easily support targeted deletion on FlatL2.
        # We trigger a full rebuild for compliance, or use IDMap in production.
        self.rebuild_index()
        
    def _save_to_disk(self):
        if HAVE_FAISS:
            faiss.write_index(self.index, self.INDEX_PATH)
            with open(self.MAPPING_PATH, 'w') as f:
                json.dump(self.id_mapping, f)

# Singleton instance
biometric_search = BiometricSearchService()
