"""SafePath 경로 탐색, 비교, 재탐색 라우터"""
from fastapi import APIRouter, Depends
from app.models.route import (
    SafeRouteRequest, SafeRouteResponse,
    CompareRequest, CompareResponse,
    RerouteRequest, RerouteResponse,
)
from app.middleware.auth import verify_firebase_token
from app.services.route_service import RouteService

router = APIRouter(prefix="/api/route", tags=["Route"])


@router.post(
    "/safe",
    response_model=SafeRouteResponse,
    summary="SafePath 경로 탐색",
    description=(
        "건강 프로필 기반으로 최적화된 안전 경로를 탐색합니다.\n\n"
        "1. Routes API로 후보 경로 3~5개 조회\n"
        "2. 경로를 100m 세그먼트로 분할\n"
        "3. Firestore 캐시에서 환경 데이터 조회\n"
        "4. Health Risk Score 산출 후 가장 안전한 경로 반환"
    ),
)
async def find_safe_route(
    request: SafeRouteRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = RouteService()
    return await service.find_safe_route(request, user["uid"])


@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="경로 비교 (최단 vs SafePath)",
    description="최단 경로와 SafePath를 나란히 비교하고 시간 차이, Risk Score 차이, 추천 사유를 반환합니다.",
)
async def compare_routes(
    request: CompareRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = RouteService()
    return await service.compare_routes(request, user["uid"])


@router.post(
    "/reroute",
    response_model=RerouteResponse,
    summary="위험 감지 시 경로 재탐색",
    description="보행 중 전방 위험이 감지되었을 때, 위험 구간을 우회하는 새로운 SafePath를 탐색합니다.",
)
async def reroute(
    request: RerouteRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = RouteService()
    return await service.reroute(request, user["uid"])
