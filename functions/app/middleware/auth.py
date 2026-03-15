"""Firebase Auth 미들웨어 — ID Token 검증"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings

security = HTTPBearer(auto_error=False)


async def verify_firebase_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Firebase ID Token 검증 → 사용자 정보 반환

    로컬 환경에서는 토큰 검증을 스킵하고 테스트 사용자를 반환합니다.
    """
    settings = get_settings()

    if settings.environment == "local":
        return {
            "uid": "1",
            "email": "test@safepath.dev",
        }

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    try:
        import firebase_admin
        from firebase_admin import auth

        # Firebase Admin SDK 초기화 (최초 1회)
        if not firebase_admin._apps:
            firebase_admin.initialize_app()

        decoded_token = auth.verify_id_token(credentials.credentials)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email"),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase ID Token: {str(e)}",
        )
