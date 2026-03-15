"""장소 검색 및 자동완성 라우터"""
from fastapi import APIRouter, Depends, Query
from app.middleware.auth import verify_firebase_token
from app.clients.maps_client import MapsClient
from app.models.search import AutocompleteResponse, PlaceDetailResponse

router = APIRouter(prefix="/api/search", tags=["Search"])


@router.get(
    "/autocomplete",
    response_model=AutocompleteResponse,
    summary="장소 검색 자동완성",
    description=(
        "사용자가 입력한 텍스트를 기반으로 목적지 후보군을 검색합니다.\n\n"
        "예: '이화' 입력 시 '이화여대 정문', '이화여대 종합과학관' 등 반환"
    ),
)
async def get_autocomplete(
    input: str = Query(..., min_length=1, description="검색어"),
    user: dict = Depends(verify_firebase_token),
):
    maps_client = MapsClient()
    predictions = await maps_client.autocomplete(input)
    return {"predictions": predictions}


@router.get(
    "/place-details",
    response_model=PlaceDetailResponse,
    summary="장소 상세 정보 조회",
    description="Google Place ID를 사용하여 장소의 이름, 주소, 좌표를 조회합니다.",
)
async def get_place_details(
    place_id: str = Query(..., description="Google Place ID"),
    user: dict = Depends(verify_firebase_token),
):
    maps_client = MapsClient()
    details = await maps_client.get_place_details(place_id)
    if not details:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Place details not found")
    return details
