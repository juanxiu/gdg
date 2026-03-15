import httpx
from fastapi import HTTPException, status
import firebase_admin
from firebase_admin import auth, firestore
from app.config import get_settings
from app.models.account import SignupRequest, LoginRequest, AuthResponse

class AccountService:
    def __init__(self):
        self.settings = get_settings()
        # Initialize Firebase Admin SDK if not already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        self.db = firestore.client()

    async def signup(self, request: SignupRequest) -> AuthResponse:
        """Firebase Admin SDK를 사용하여 계정을 생성합니다."""
        try:
            # 1. Firebase Auth에 사용자 생성
            user_record = auth.create_user(
                email=request.email,
                password=request.password,
                display_name=request.displayName
            )

            # 2. 로그인 처리를 위해 ID Token 획득 (REST API 사용)
            # Admin SDK는 직접적인 로그인을 지원하지 않으므로 REST API를 호출합니다.
            token = await self._get_id_token(request.email, request.password)

            return AuthResponse(
                uid=user_record.uid,
                email=user_record.email,
                token=token,
                isNewUser=True
            )
        except auth.EmailAlreadyExistsError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 존재하는 이메일입니다."
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"회원가입 중 오류가 발생했습니다: {str(e)}"
            )

    async def login(self, request: LoginRequest) -> AuthResponse:
        """Firebase Auth REST API를 사용하여 로그인을 수행하고 ID Token을 반환합니다."""
        try:
            token = await self._get_id_token(request.email, request.password)
            user_record = auth.get_user_by_email(request.email)

            return AuthResponse(
                uid=user_record.uid,
                email=user_record.email,
                token=token,
                isNewUser=False
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 올바르지 않습니다."
            )

    async def delete_account(self, uid: str):
        """사용자 계정과 관련 데이터를 삭제합니다."""
        try:
            # 1. Firestore 데이터 삭제 (예시: 프로필)
            # TODO: 서비스별로 삭제 로직을 확장할 수 있습니다.
            profiles_ref = self.db.collection(f"{self.settings.firestore_collection_prefix}profiles")
            user_profiles = profiles_ref.where("userId", "==", uid).stream()
            for doc in user_profiles:
                doc.reference.delete()

            # 2. Firebase Auth 사용자 삭제
            auth.delete_user(uid)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"계정 삭제 중 오류가 발생했습니다: {str(e)}"
            )

    async def _get_id_token(self, email: str, password: str) -> str:
        """Firebase Auth REST API를 호출하여 ID Token을 가져옵니다."""
        if not self.settings.firebase_web_api_key:
            # 로컬 개발 시 API 키가 없으면 Mock 토큰 반환 (환경에 따라 조정 가능)
            if self.settings.environment == "local":
                return "mock_firebase_token_for_local_dev"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="FIREBASE_WEB_API_KEY가 설정되지 않았습니다."
            )

        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.settings.firebase_web_api_key}"
        data = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
            if response.status_code != 200:
                raise Exception(response.json().get("error", {}).get("message", "Unknown error"))
            
            return response.json().get("idToken")
