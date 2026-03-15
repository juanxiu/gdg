"""건강 프로필 CRUD 라우터"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.profile import (
    ProfileCreateRequest, ProfileCreateResponse,
    ProfileResponse, ProfileUpdateRequest,
)
from app.middleware.auth import verify_firebase_token
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/profile", tags=["Profile"])


@router.post(
    "",
    response_model=ProfileCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="건강 프로필 생성",
    description="질환 유형, 연령, 민감도 레벨을 포함한 건강 프로필을 생성합니다. customWeights가 null이면 AI가 질환 기반으로 자동 산출합니다.",
)
async def create_profile(
    request: ProfileCreateRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = ProfileService()
    return await service.create(user["uid"], request)


@router.get(
    "/{profile_id}",
    response_model=ProfileResponse,
    summary="건강 프로필 조회",
)
async def get_profile(
    profile_id: str,
    user: dict = Depends(verify_firebase_token),
):
    service = ProfileService()
    result = await service.get(profile_id, user["uid"])
    if not result:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return result


@router.put(
    "/{profile_id}",
    response_model=ProfileResponse,
    summary="건강 프로필 수정",
)
async def update_profile(
    profile_id: str,
    request: ProfileUpdateRequest,
    user: dict = Depends(verify_firebase_token),
):
    service = ProfileService()
    result = await service.update(profile_id, user["uid"], request)
    if not result:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return result


@router.delete(
    "/{profile_id}",
    summary="건강 프로필 삭제",
)
async def delete_profile(
    profile_id: str,
    user: dict = Depends(verify_firebase_token),
):
    service = ProfileService()
    success = await service.delete(profile_id, user["uid"])
    if not success:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return {"message": "프로필이 삭제되었습니다."}
