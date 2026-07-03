import cv2
import numpy as np

try:
    from deepface import DeepFace
    HAVE_FACE_REC = True
except ImportError:
    HAVE_FACE_REC = False

def get_face_encoding(image_bytes):
    """
    Extracts a face embedding using DeepFace (Facenet).
    Returns {"success": True, "encoding": [float, ...]} or {"success": False, "error": str}
    """
    if not HAVE_FACE_REC:
        return {"success": False, "error": "deepface library not installed"}
        
    try:
        np_img = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if img is None:
            return {"success": False, "error": "Invalid image format"}
            
        # DeepFace represent extracts embeddings
        # enforce_detection=True ensures there is a face
        results = DeepFace.represent(img_path=img, model_name="Facenet", enforce_detection=True)
        
        if not results:
            return {"success": False, "error": "No face detected"}
        if len(results) > 1:
            return {"success": False, "error": "Multiple faces detected. Please ensure only one face is visible."}
            
        return {
            "success": True,
            "encoding": results[0]['embedding']
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def compare_faces(known_encoding_list, face_encoding_list, tolerance=0.40):
    """
    Compare two Facenet embeddings using Cosine similarity.
    DeepFace Facenet recommended cosine threshold is 0.40.
    """
    if not HAVE_FACE_REC:
        return {"success": False, "error": "deepface library not installed"}
        
    try:
        from deepface.commons import distance as dst
        
        # known_encoding_list can be a list of embeddings (if multi-angle is used)
        # For simplicity, we just check the first one if it's nested
        if len(known_encoding_list) > 0 and isinstance(known_encoding_list[0], list):
            # Average multi-angle embeddings into a single mean vector
            known_enc = np.mean(known_encoding_list, axis=0)
        else:
            known_enc = np.array(known_encoding_list)
            
        unknown_enc = np.array(face_encoding_list)
        
        # Calculate Cosine distance
        distance = dst.findCosineDistance(known_enc, unknown_enc)
        is_match = distance <= tolerance
        
        return {
            "success": True,
            "match": bool(is_match),
            "distance": float(distance)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

