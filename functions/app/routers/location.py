"""실시간 위치 업데이트 & 전방 위험 감지 라우터"""
from fastapi import APIRouter, Depends, Query
from app.models.route import LocationUpdateRequest, LocationUpdateResponse
from app.middleware.auth import verify_firebase_token
from app.services.route_service import RouteService
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


@router.post(
    "/update",
    response_model=LocationUpdateResponse,
    summary="실시간 위치 업데이트",
    description=(
        "내비게이션 중 30초 간격으로 위치를 전송합니다.\n\n"
        "서버는 전방 100~500m의 환경 상태를 선제 확인하여 위험 감지 시 "
        "`HAZARD_AHEAD` 상태와 함께 우회 경로 재탐색을 권장합니다."
    ),
)
async def update_location(
    request: LocationUpdateRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = RouteService()
    return await service.process_location_update(request)
