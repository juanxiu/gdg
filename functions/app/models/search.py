from pydantic import BaseModel, Field
from typing import List, Optional


class AutocompletePrediction(BaseModel):
    """장소 자동완성 제안"""
    description: str = Field(..., description="사용자에게 보여줄 장소 이름", examples=["이화여자대학교 종합과학관"])
    place_id: str = Field(..., description="Google Place ID (상세 정보 조회용)")
    main_text: str = Field(..., description="주요 명칭")
    secondary_text: Optional[str] = Field(None, description="부수적 주소 정보")


class AutocompleteResponse(BaseModel):
    """자동완성 응답"""
    predictions: List[AutocompletePrediction]


class PlaceDetailResponse(BaseModel):
    """장소 상세 정보 (좌표 포함)"""
    place_id: str
    name: str
    formatted_address: str
    lat: float
    lng: float
