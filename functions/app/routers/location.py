"""실시간 위치 업데이트 & 전방 위험 감지 라우터"""
from fastapi import APIRouter, Depends, Query
from app.middleware.auth import verify_firebase_token
from app.services.environment_service import EnvironmentService
from app.models.environment import CurrentEnvironmentResponse

router = APIRouter(prefix="/api/location", tags=["Location"])


@router.get(
    "/home",
    response_model=CurrentEnvironmentResponse,
    summary="홈화면 지역 정보 조회",
    description="사용자의 현재 위치를 기반으로 실시간 대기질, 기상, 꽃가루 등 안전 정보를 조회합니다.",
)
async def get_home_location_info(
    lat: float = Query(..., description="위도"),
    lng: float = Query(..., description="경도"),
    user: dict = Depends(verify_firebase_token),
):
    service = EnvironmentService()
    return await service.get_current(lat, lng)
