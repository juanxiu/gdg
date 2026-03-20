from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.common import Severity


class ConditionDetail(BaseModel):
    """질환 상세 정보"""
    enabled: bool = Field(False, description="활성화 여부")
    severity: Severity = Field(Severity.LOW, description="심각도 (low/medium/high)")


class HealthConditions(BaseModel):
    """건강 상태 (질환 유형별)"""
    respiratory: ConditionDetail = Field(default_factory=ConditionDetail, description="호흡기 질환 (천식/COPD)")
    cardiovascular: ConditionDetail = Field(default_factory=ConditionDetail, description="심혈관 질환")
    heatVulnerable: ConditionDetail = Field(default_factory=ConditionDetail, description="온열 질환 취약")
    allergyPollen: ConditionDetail = Field(default_factory=ConditionDetail, description="꽃가루 알레르기")


class CustomWeights(BaseModel):
    """환경 요인별 커스텀 가중치"""
    pm25: float = Field(2.0, ge=0, le=25, description="PM2.5 가중치")
    pm10: float = Field(2.0, ge=0, le=25, description="PM10 가중치")
    no2: float = Field(1.5, ge=0, le=25, description="NO2 가중치")
    o3: float = Field(1.0, ge=0, le=25, description="O3 가중치")
    pollen: float = Field(1.0, ge=0, le=25, description="꽃가루 가중치")
    temperature: float = Field(2.0, ge=0, le=25, description="체감온도 가중치")
    slope: float = Field(1.0, ge=0, le=25, description="경사도 가중치")
    shade: float = Field(1.5, ge=0, le=25, description="그늘 가중치")


# --- Request ---


class ProfileCreateRequest(BaseModel):
    """건강 프로필 생성 요청"""
    displayName: str = Field(..., min_length=1, max_length=50, description="프로필 이름", examples=["박영수"])
    age: int = Field(..., ge=1, le=150, description="나이", examples=[72])
    conditions: HealthConditions = Field(..., description="질환 유형별 설정")
    customWeights: Optional[CustomWeights] = Field(None, description="null이면 AI가 자동 산출")
    guardianId: Optional[str] = Field(None, description="보호자 사용자 ID")


class ProfileUpdateRequest(BaseModel):
    """건강 프로필 수정 요청"""
    displayName: Optional[str] = Field(None, min_length=1, max_length=50)
    age: Optional[int] = Field(None, ge=1, le=150)
    conditions: Optional[HealthConditions] = None
    customWeights: Optional[CustomWeights] = None


# --- Response ---


class ProfileResponse(BaseModel):
    """건강 프로필 응답"""
    profile_id: str
    userId: str
    displayName: str
    age: int
    conditions: HealthConditions
    customWeights: CustomWeights
    guardianId: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime


class ProfileCreateResponse(BaseModel):
    """프로필 생성 응답"""
    profile_id: str
    message: str = "건강 프로필이 생성되었습니다."
    autoWeights: CustomWeights
