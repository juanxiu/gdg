from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class LatLng(BaseModel):
    """위도/경도 좌표"""
    lat: float = Field(..., ge=-90, le=90, description="위도", examples=[37.4979])
    lng: float = Field(..., ge=-180, le=180, description="경도", examples=[127.0276])


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DANGER = "DANGER"


class TravelMode(str, Enum):
    WALK = "WALK"
    WHEELCHAIR = "WHEELCHAIR"
    DRIVE = "DRIVE"
    BICYCLE = "BICYCLE"
    TRANSIT = "TRANSIT"


class HazardType(str, Enum):
    AIR_QUALITY = "AIR_QUALITY"
    HEAT = "HEAT"
    POLLEN = "POLLEN"
    CONSTRUCTION = "CONSTRUCTION"





class ErrorResponse(BaseModel):
    """공통 에러 응답"""
    code: int
    status: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
