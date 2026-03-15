from pydantic import BaseModel, Field
from typing import List, Optional


class TripSummary(BaseModel):
    """개별 트립 요약"""
    tripId: str
    startTime: str
    endTime: str
    origin: str
    destination: str
    distance: int
    duration: int
    healthRiskScore: int
    rerouteCount: int = 0


class ExposureSummary(BaseModel):
    """환경 노출 요약"""
    avgPm25: float
    maxPm25: float
    avgTemperature: float
    maxFeelsLike: float
    totalPollenExposure: str
    avgShadeRatio: float


class WeeklyReportSummary(BaseModel):
    """주간 요약 통계"""
    totalTrips: int
    totalDistance: int
    totalDuration: int
    avgHealthRiskScore: int
    hazardsAvoided: int
    healthMinutesSaved: int


class WeeklyReportResponse(BaseModel):
    """주간 건강 경로 리포트 응답"""
    period: str = Field(..., description="조회 기간 (예: 2024-03-08 ~ 2024-03-14)")
    profileId: str
    summary: WeeklyReportSummary
    exposureSummary: ExposureSummary
    trips: List[TripSummary]
    recommendation: str
    isInitialUser: bool = False
