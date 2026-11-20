import os
import cv2
import numpy as np
from django.conf import settings

HAVE_FACE_REC = True

_detector = None
_recognizer = None

def get_face_models():
    """
    Lazy singleton loader for OpenCV YuNet Face Detector and SFace Face Recognizer.
    Runs 100% locally and offline via OpenCV DNN C++ engine, with 0 external network dependencies.
    """
    global _detector, _recognizer
    if _detector is None or _recognizer is None:
        det_path = getattr(
            settings,
            'FACE_DETECTOR_PATH',
            os.path.join(settings.BASE_DIR, 'media', 'face_models', 'face_detection_yunet_2023mar.onnx')
        )
        rec_path = getattr(
            settings,
            'FACE_RECOGNIZER_PATH',
            os.path.join(settings.BASE_DIR, 'media', 'face_models', 'face_recognition_sface_2021dec.onnx')
        )

        if not os.path.exists(det_path) or not os.path.exists(rec_path):
            raise FileNotFoundError(f"Face model ONNX files not found at {det_path} or {rec_path}")

        _detector = cv2.FaceDetectorYN.create(
            model=det_path,
            config='',
            input_size=(320, 320),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000
        )
        _recognizer = cv2.FaceRecognizerSF.create(
            model=rec_path,
            config=''
        )

    return _detector, _recognizer


def get_face_encoding(image_bytes):
    """
    Extracts a 128-dimensional facial embedding vector using OpenCV YuNet + SFace.
    Automatically handles multi-face frames by selecting the primary (largest area) face,
    allowing clean recognition even with background activity.
    Returns:
        {"success": True, "encoding": [float, ...], "facial_area": dict, "frame_dims": dict}
    or
        {"success": False, "error": str}
    """
    try:
        detector, recognizer = get_face_models()

        np_img = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if img is None:
            return {"success": False, "error": "Invalid image format"}

        h, w = img.shape[:2]
        detector.setInputSize((w, h))
        _, faces = detector.detect(img)

        if faces is None or len(faces) == 0:
            return {"success": False, "error": "No face detected in camera frame. Please align your face inside the guide."}

        # Select primary face by bounding box area (w * h) to pick the person in front
        sorted_faces = sorted(faces, key=lambda f: float(f[2]) * float(f[3]), reverse=True)
        primary_face = sorted_faces[0]

        # SFace face alignment and feature extraction
        aligned_face = recognizer.alignCrop(img, primary_face)
        feature_vector = recognizer.feature(aligned_face)

        if feature_vector is None or len(feature_vector) == 0:
            return {"success": False, "error": "Could not extract facial features. Please ensure proper lighting."}

        flat_encoding = feature_vector.flatten().tolist()
        facial_area = {
            "x": int(primary_face[0]),
            "y": int(primary_face[1]),
            "w": int(primary_face[2]),
            "h": int(primary_face[3])
        }

        return {
            "success": True,
            "encoding": flat_encoding,
            "facial_area": facial_area,
            "frame_dims": {"width": w, "height": h}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def compare_faces(known_encoding_list, face_encoding_list, tolerance=0.50):
    """
    Compares face embedding vectors using Cosine distance.
    SFace embeddings yield high cosine similarity (> 0.60 to 0.95) for matches.
    Distance = 1.0 - CosineSimilarity.
    A tolerance of 0.50 (similarity >= 0.50) provides robust, fast matching.
    """
    try:
        if not known_encoding_list or not face_encoding_list:
            return {"success": False, "error": "Empty encodings provided"}

        live_arr = np.array(face_encoding_list, dtype=np.float32).flatten()
        norm_live = np.linalg.norm(live_arr)
        if norm_live == 0:
            return {"success": False, "error": "Invalid live encoding vector"}

        # Handle nested list of known embeddings (e.g. multi-angle or multiple snapshots)
        if isinstance(known_encoding_list[0], (list, np.ndarray)):
            distances = []
            for known in known_encoding_list:
                k_arr = np.array(known, dtype=np.float32).flatten()
                if len(k_arr) != len(live_arr):
                    continue
                norm_k = np.linalg.norm(k_arr)
                if norm_k > 0:
                    sim = float(np.dot(k_arr, live_arr) / (norm_k * norm_live))
                    distances.append(max(0.0, 1.0 - sim))
            
            if not distances:
                return {"success": False, "error": "Encoding vector dimension mismatch"}
            best_dist = min(distances)
        else:
            k_arr = np.array(known_encoding_list, dtype=np.float32).flatten()
            if len(k_arr) != len(live_arr):
                return {"success": False, "error": "Encoding vector dimension mismatch"}
            norm_k = np.linalg.norm(k_arr)
            if norm_k > 0:
                sim = float(np.dot(k_arr, live_arr) / (norm_k * norm_live))
                best_dist = max(0.0, 1.0 - sim)
            else:
                best_dist = 1.0

        is_match = best_dist <= tolerance

        return {
            "success": True,
            "match": bool(is_match),
            "distance": float(best_dist),
            "similarity": float(1.0 - best_dist)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
