import math
from datetime import datetime
from typing import Optional

class VelocityCheckService:
    """
    Wave 5: Hardened GPS Security.
    Detects impossible travel velocity to prevent API location spoofing.
    """
    
    MAX_POSSIBLE_SPEED_KMH = 900  # Max commercial flight speed
    
    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Returns distance in meters."""
        R = 6371000 # Radius of earth in meters
        phi_1 = math.radians(lat1)
        phi_2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2.0) ** 2
        return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    @classmethod
    def is_travel_possible(cls, 
                           lat1: float, lng1: float, time1: datetime, 
                           lat2: float, lng2: float, time2: datetime) -> tuple[bool, str]:
        """
        Validates if the user could have physically traveled between the two GPS points
        in the elapsed time.
        """
        distance_meters = cls.haversine(lat1, lng1, lat2, lng2)
        time_diff_hours = abs((time2 - time1).total_seconds()) / 3600.0
        
        if time_diff_hours == 0:
            if distance_meters > 100:  # Allow 100m variance for instant punches due to GPS jitter
                return False, "Impossible Travel: Large distance jump in 0 seconds."
            return True, "Valid"
            
        speed_kmh = (distance_meters / 1000.0) / time_diff_hours
        
        if speed_kmh > cls.MAX_POSSIBLE_SPEED_KMH:
            return False, f"Impossible Travel: Required speed {int(speed_kmh)} km/h exceeds human limits."
            
        return True, "Valid"
