from fastapi import APIRouter, Depends, status
from app.middleware.auth import verify_firebase_token
from app.models.account import SignupRequest, LoginRequest, AuthResponse
from app.services.account_service import AccountService

router = APIRouter(prefix="/api/account", tags=["Account"])


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
    description="이메일과 비밀번호를 사용하여 새로운 계정을 생성합니다.",
)
async def signup(request: SignupRequest):
    service = AccountService()
    return await service.signup(request)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="로그인",
    description="이메일과 비밀번호를 사용하여 로그인을 수행하고 토큰을 반환합니다.",
)
async def login(request: LoginRequest):
    service = AccountService()
    return await service.login(request)


@router.delete(
    "",
    summary="계정 삭제",
    description="사용자 계정 및 모든 관련 데이터(프로필, 경로 이력)를 삭제합니다.",
)
async def delete_account(
    user: dict = Depends(verify_firebase_token),
):
    service = AccountService()
    await service.delete_account(user["uid"])
    return {
        "message": "계정이 성공적으로 삭제되었습니다.",
        "userId": user["uid"],
    }
