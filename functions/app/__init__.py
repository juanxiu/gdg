from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import traceback
import logging
from app.config import get_settings
from app.routers import profile, route, location, environment, report, account, search, navigation


def create_app() -> FastAPI:
    """FastAPI 앱 팩토리 — Swagger UI 설정 포함"""
    settings = get_settings()

    # Cloud Run/Local 환경에 따라 서버 목록 설정 (Production을 우선순위로)
    servers = [
        {
            "url": "https://api-190228148301.asia-northeast3.run.app",
            "description": "☁️ GCP Cloud Run (Production)",
        },
        {
            "url": "http://localhost:8080",
            "description": "🖥️ 로컬 개발 서버",
        },
    ]

    app = FastAPI(
        title="SafePath API",
        description=(
            "🌿 **기후 취약계층을 위한 건강 최우선 경로 탐색 API**\n\n"
            "SDG 3 (건강과 웰빙) + SDG 13 (기후 행동)\n\n"
            "---\n\n"
            "### 주요 기능\n"
            "- 🗺️ **SafePath 경로 탐색**: 건강 위험도가 가장 낮은 최적 경로 안내\n"
            "- 📊 **경로 비교**: 최단 경로 vs SafePath 비교\n"
            "- 🌬️ **실시간 환경 데이터**: 대기질, 꽃가루, 온도 정보\n"
            "- 👤 **건강 프로필**: 질환별 맞춤 경로 가중치\n"
            "- 📋 **일일 건강 리포트**: 누적 환경 노출 요약\n\n"
            "---\n\n"
            "### 인증\n"
            "모든 API는 `Authorization: Bearer <Firebase ID Token>` 헤더가 필요합니다."
        ),
        version="1.0.0",
        servers=servers,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "Profile", "description": "건강 프로필 CRUD"},
            {"name": "Route", "description": "SafePath 경로 탐색, 비교, 재탐색"},
            {"name": "Location", "description": "실시간 위치 업데이트 & 전방 위험 감지"},
            {"name": "Environment", "description": "환경 데이터 조회 (대기질, 꽃가루, 히트맵)"},
            {"name": "Report", "description": "일일 건강 경로 리포트"},
            {"name": "Account", "description": "계정 관리"},
            {"name": "Search", "description": "장소 검색 및 자동완성"},
            {"name": "Navigation", "description": "실시간 WebSocket 내비게이션"},
        ],
    )

    # 1. 라우터 등록
    app.include_router(profile.router)
    app.include_router(route.router)
    app.include_router(location.router)
    app.include_router(environment.router)
    app.include_router(report.router)
    app.include_router(account.router)
    app.include_router(search.router)
    app.include_router(navigation.router)

    # 2. 예외 처리기 등록
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger = logging.getLogger("uvicorn")
        
        # HTTPException인 경우 해당 정보를 그대로 반환하여 404 등이 500으로 바뀌지 않게 함
        if hasattr(exc, "status_code") and hasattr(exc, "detail"):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )
            
        logger.error(f"Global Exception: {str(exc)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": "FRS_004", "message": f"서버 전역 오류: {str(exc)}", "data": traceback.format_exc()}
        )

    # 3. 미들웨어 등록 (역순으로 실행됨)
    # 로깅 미들웨어
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger = logging.getLogger("uvicorn")
        logger.info(f"Request: {request.method} {request.url}")
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(f"Unhandled Exception: {str(e)}")
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"code": "FRS_004", "message": f"서버 내부 오류: {str(e)}", "data": traceback.format_exc()}
            )

    # CORS 미들웨어 (가장 마지막에 추가하여 가장 먼저 실행되도록 함)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",
            "http://localhost:5173",
            "https://gdg-frontend-vercel.vercel.app",  # Vercel 프론트엔드 추가
            "https://api-190228148301.asia-northeast3.run.app",
        ],
        allow_origin_regex="https?://.*",  # 모든 origin을 허용하면서 credentials 지원
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["Health Check"])
    async def health_check():
        """서버 상태 확인"""
        return {
            "status": "healthy",
            "service": "SafePath API",
            "version": "1.0.0",
            "environment": settings.environment,
        }

    return app
