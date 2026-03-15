from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class EnvironmentalDataType(str, Enum):
    """환경 영역 데이터 타입"""
    AQI = "aqi"
    POLLEN = "pollen"
    TEMPERATURE = "temperature"
    SHADE = "shade"


class AirQualityData(BaseModel):
    """대기질 데이터"""
    aqi: int = Field(..., ge=0, description="대기질 지수")
    category: str = Field(..., description="대기질 카테고리")
    pm25: float = Field(..., ge=0)
    pm10: float = Field(..., ge=0)
    no2: float = Field(..., ge=0)
    o3: float = Field(..., ge=0)
    co: float = Field(..., ge=0)
    so2: float = Field(..., ge=0)
    dominantPollutant: str = Field(..., description="주요 오염물질")


class WeatherData(BaseModel):
    """기상 데이터"""
    temperature: float
    feelsLike: float
    humidity: int = Field(..., ge=0, le=100)
    uvIndex: int = Field(..., ge=0)
    windSpeed: float = Field(..., ge=0)
    windDirection: str


class PollenTypeDetail(BaseModel):
    """개별 꽃가루 유형"""
    name: str
    level: int = Field(..., ge=0, le=5)


class PollenData(BaseModel):
    """꽃가루 데이터"""
    overallLevel: int = Field(..., ge=0, le=5)
    overallCategory: str
    types: List[PollenTypeDetail] = Field(default_factory=list)


class HealthAdvisory(BaseModel):
    """질환별 건강 조언"""
    respiratory: Optional[str] = None
    heatVulnerable: Optional[str] = None
    cardiovascular: Optional[str] = None


class CurrentEnvironmentResponse(BaseModel):
    """현재 위치 환경 데이터 응답"""
    location: dict
    timestamp: str
    airQuality: AirQualityData
    weather: WeatherData
    pollen: PollenData
    healthAdvisory: HealthAdvisory


class EnvironmentAreaInfo(BaseModel):
    """환경 영역 정보 (그리드 포인트)"""
    lat: float
    lng: float
    value: float
    level: str
    color: str


class EnvironmentAreaResponse(BaseModel):
    """환경 영역 조회 응답"""
    type: EnvironmentalDataType
    bounds: dict
    gridSize: int
    areas: List[EnvironmentAreaInfo]
    generatedAt: str
