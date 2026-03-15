"""계정 관리 라우터"""
from fastapi import APIRouter, Depends
from app.middleware.auth import verify_firebase_token

from app.models.account import SignupRequest, LoginRequest, AuthResponse

router = APIRouter(prefix="/api/account", tags=["Account"])


@router.post(
    "/signup",
    response_model=AuthResponse,
    summary="회원가입",
    description="이메일과 비밀번호를 사용하여 새로운 계정을 생성합니다.",
)
async def signup(request: SignupRequest):
    # TODO: Firebase Auth 계정 생성 로직 연동
    return AuthResponse(
        uid="new_user_id",
        email=request.email,
        token="mock_firebase_token",
        isNewUser=True
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="로그인",
    description="이메일과 비밀번호를 사용하여 로그인을 수행하고 토큰을 반환합니다.",
)
async def login(request: LoginRequest):
    # TODO: Firebase Auth 로그인 로직 연동
    return AuthResponse(
        uid="existing_user_id",
        email=request.email,
        token="mock_firebase_token",
        isNewUser=False
    )



@router.delete(
    "",
    summary="계정 삭제",
    description="사용자 계정 및 모든 관련 데이터(프로필, 경로 이력)를 삭제합니다. GDPR/개인정보 보호법 준수.",
)
async def delete_account(
    user: dict = Depends(verify_firebase_token),
):
    # TODO: Firestore에서 사용자 관련 데이터 전부 삭제
    # TODO: Firebase Auth 사용자 삭제
    return {
        "message": "계정이 삭제되었습니다.",
        "userId": user["uid"],
    }
