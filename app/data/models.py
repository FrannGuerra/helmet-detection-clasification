from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Camera:
    id: int
    name: str
    source: str
    lat: float
    lng: float

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'source': self.source,
            'lat': self.lat,
            'lng': self.lng
        }

@dataclass
class Detection:
    timestamp: float
    bbox: List[float] 
    class_name: str
    confidence: float
    helmet_status: Optional[str] = None
    helmet_confidence: float = 0.0
    camera_id: int = 0
    
    def to_dict(self):
        return {
            'timestamp': self.timestamp,
            'bbox': self.bbox,
            'class_name': self.class_name,
            'confidence': self.confidence,
            'helmet_status': self.helmet_status,
            'helmet_confidence': self.helmet_confidence,
            'camera_id': self.camera_id
        }

@dataclass
class Metrics:
    total_riders: int = 0
    riders_with_helmet: int = 0
    riders_without_helmet: int = 0
    compliance_rate: float = 0.0
    camera_id: int = 0
    
    def update_compliance(self):
        if self.total_riders > 0:
            self.compliance_rate = (self.riders_with_helmet / self.total_riders) * 100
        else:
            self.compliance_rate = 0.0
    
    def to_dict(self):
        return {
            'total_riders': self.total_riders,
            'riders_with_helmet': self.riders_with_helmet,
            'riders_without_helmet': self.riders_without_helmet,
            'compliance_rate': round(self.compliance_rate, 2),
            'camera_id': self.camera_id
        }