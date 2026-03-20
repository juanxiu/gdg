from pydantic import BaseModel, Field
from typing import Optional, List
from app.models.common import LatLng, RiskLevel, TravelMode, HazardType


# --- 환경 데이터 (세그먼트별) ---


class SegmentEnvironment(BaseModel):
    """세그먼트별 환경 데이터"""
    aqi: int = Field(0, ge=0, description="대기질 지수")
    pm25: float = Field(0.0, ge=0, description="PM2.5 (μg/m³)")
    pm10: float = Field(0.0, ge=0, description="PM10 (μg/m³)")
    no2: float = Field(0.0, ge=0, description="NO2 (ppb)")
    o3: float = Field(0.0, ge=0, description="O3 (ppb)")
    temperature: float = Field(20.0, description="기온 (°C)")
    feelsLike: float = Field(20.0, description="체감온도 (°C)")
    humidity: int = Field(50, ge=0, le=100, description="습도 (%)")
    pollenLevel: int = Field(0, ge=0, le=5, description="꽃가루 레벨 (0~5)")
    pollenTypes: List[str] = Field(default_factory=list, description="꽃가루 종류")
    shadeRatio: float = Field(0.0, ge=0, le=1, description="그늘 비율 (0~1)")
    slope: float = Field(0.0, ge=0, description="경사도 (%)")


class RouteSegment(BaseModel):
    """경로 세그먼트"""
    segmentId: str
    startLatLng: LatLng
    endLatLng: LatLng
    distance: int = Field(..., description="거리 (m)")
    duration: int = Field(..., description="소요 시간 (초)")
    riskScore: int = Field(..., ge=0, le=100, description="Risk Score (0~100)")
    riskLevel: RiskLevel
    environment: SegmentEnvironment
    instruction: str = Field(..., description="안내 문구")


class RouteWarning(BaseModel):
    """경로 주의사항"""
    type: str
    message: str
    segmentIds: List[str] = Field(default_factory=list)


class RouteMetadata(BaseModel):
    """경로 메타데이터"""
    profileApplied: str
    weightsUsed: dict
    dataFreshness: str
    computedIn: float = Field(..., description="응답 소요 시간 (초)")


# --- SafePath 경로 탐색 ---


class RouteOptions(BaseModel):
    """경로 탐색 옵션"""
    maxDetourMinutes: int = Field(10, ge=1, le=30, description="최대 우회 허용 시간 (분)")
    avoidStairs: bool = Field(False, description="계단 회피")
    preferParks: bool = Field(False, description="공원/녹지 선호")
    travelMode: TravelMode = Field(TravelMode.TRANSIT, description="이동 수단")


class SafeRouteRequest(BaseModel):
    """SafePath 경로 탐색 요청"""
    origin: LatLng = Field(..., description="출발지")
    destination: LatLng = Field(..., description="도착지")
    profile_id: str = Field(..., description="건강 프로필 ID")
    departureTime: Optional[str] = Field(None, description="출발 예정 시간 (ISO 8601)")
    options: RouteOptions = Field(default_factory=RouteOptions)


class SafePathResult(BaseModel):
    """SafePath 경로 결과"""
    routeId: str
    polyline: str = Field(..., description="Google Encoded Polyline")
    totalDistance: int = Field(..., description="총 거리 (m)")
    totalDuration: int = Field(..., description="총 소요 시간 (초)")
    healthRiskScore: int = Field(..., ge=0, le=100)
    summary: str
    segments: List[RouteSegment]
    warnings: List[RouteWarning] = Field(default_factory=list)


class SafeRouteResponse(BaseModel):
    """SafePath 경로 탐색 응답"""
    paths: List[SafePathResult] = Field(..., description="안전 점수 순으로 정렬된 경로 후보 목록")
    metadata: RouteMetadata


# --- 경로 비교 ---


class CompareRequest(BaseModel):
    """경로 비교 요청"""
    origin: LatLng
    destination: LatLng
    profile_id: str
    departureTime: Optional[str] = None
    options: RouteOptions = Field(default_factory=RouteOptions)


class RouteComparisonItem(BaseModel):
    """비교용 경로 요약"""
    routeId: str
    polyline: str
    totalDistance: int
    totalDuration: int
    healthRiskScore: int
    avgAqi: int
    avgShadeRatio: float
    avgPollenLevel: int
    riskLevel: RiskLevel


class ComparisonDelta(BaseModel):
    """비교 차이"""
    distanceDiff: int
    durationDiff: int
    riskScoreDiff: int
    recommendation: str
    reason: str


class CompareResponse(BaseModel):
    """경로 비교 응답"""
    comparison: dict  # shortestRoute, safePath, delta


# --- 경로 재탐색 ---


class HazardDetail(BaseModel):
    """위험 상세"""
    type: HazardType
    detectedAt: LatLng
    severity: RiskLevel
    details: Optional[dict] = None


class RerouteRequest(BaseModel):
    """경로 재탐색 요청"""
    currentRouteId: str
    currentLocation: LatLng
    destination: LatLng
    profile_id: str
    hazard: HazardDetail


class RerouteResponse(BaseModel):
    """경로 재탐색 응답"""
    reroutedPath: SafePathResult
    originalRemainingRisk: int
    newRisk: int
    improvement: int


# --- 위치 업데이트 ---


class LocationUpdateRequest(BaseModel):
    """실시간 위치 업데이트 요청"""
    routeId: str
    profile_id: str
    location: LatLng
    heading: Optional[float] = Field(None, ge=0, le=360, description="이동 방향 (°)")
    speed: Optional[float] = Field(None, ge=0, description="이동 속도 (m/s)")
    timestamp: Optional[str] = None


class AheadHazard(BaseModel):
    """전방 위험"""
    type: HazardType
    severity: RiskLevel
    distanceAhead: int
    location: LatLng
    details: Optional[dict] = None


class AheadScan(BaseModel):
    """전방 스캔 결과"""
    scannedDistance: int
    hazardDetected: bool
    hazards: List[AheadHazard] = Field(default_factory=list)


class LocationUpdateResponse(BaseModel):
    """위치 업데이트 응답원"""
    status: str = Field(..., description="ON_ROUTE / HAZARD_AHEAD / OFF_ROUTE")
    message: str = Field("", description="LLM 생성 맞춤형 알림 메시지")
    currentSegmentId: str
    nextSegmentRisk: RiskLevel
    aheadScan: AheadScan
    rerouteRecommended: bool = False
    eta: int = Field(..., description="도착 예상 시간 (초)")
    remainingDistance: int = Field(..., description="남은 거리 (m)")
