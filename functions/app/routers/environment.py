"""환경 데이터 조회 라우터 (대기질, 꽃가루, 영역 조회)"""
from fastapi import APIRouter, Depends, Query
from app.models.environment import CurrentEnvironmentResponse, EnvironmentAreaResponse, EnvironmentalDataType
from app.middleware.auth import verify_firebase_token
from app.services.environment_service import EnvironmentService

router = APIRouter(prefix="/api/environment", tags=["Environment"])


@router.get(
    "/current",
    response_model=CurrentEnvironmentResponse,
    summary="현재 위치 환경 데이터",
    description="지정된 좌표의 현재 대기질(AQI, PM2.5 등), 기상(온도, 체감온도), 꽃가루 농도, 질환별 건강 조언을 반환합니다.",
)
async def get_current_environment(
    lat: float = Query(..., ge=-90, le=90, description="위도", examples=[37.4979]),
    lng: float = Query(..., ge=-180, le=180, description="경도", examples=[127.0276]),
    user: dict = Depends(verify_firebase_token),
):
    service = EnvironmentService()
    return await service.get_current(lat, lng)


@router.get(
    "/area",
    response_model=EnvironmentAreaResponse,
    summary="미세먼지 및 꽃가루 영역 조회",
    description="지정된 영역(bounds)의 격자별 환경 데이터를 조회합니다. 타입: AQI, POLLEN, TEMPERATURE, SHADE",
)
async def get_area_data(
    swLat: float = Query(..., description="남서 꼭짓점 위도"),
    swLng: float = Query(..., description="남서 꼭짓점 경도"),
    neLat: float = Query(..., description="북동 꼭짓점 위도"),
    neLng: float = Query(..., description="북동 꼭짓점 경도"),
    zoom: int = Query(..., ge=12, le=18, description="줌 레벨"),
    type: EnvironmentalDataType = Query(..., description="데이터 타입"),
    user: dict = Depends(verify_firebase_token),
):
    service = EnvironmentService()
    return await service.get_area_data(swLat, swLng, neLat, neLng, zoom, type)
