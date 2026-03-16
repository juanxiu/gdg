"""주간 건강 경로 리포트 라우터"""
from fastapi import APIRouter, Depends, Query
from app.middleware.auth import verify_firebase_token
from app.services.report_service import ReportService
from app.models.report import WeeklyReportResponse

router = APIRouter(prefix="/api/report", tags=["Report"])


@router.get(
    "/weekly",
    response_model=WeeklyReportResponse,
    summary="홈화면 주중 리포트",
    description="최근 7일 동안 걸은 경로의 누적 환경 노출 요약, 트립 목록, 건강 권장사항을 반환합니다.",
)
async def get_weekly_report(
    profile_id: str = Query(..., alias="profile_id", description="건강 프로필 ID"),
    date: str = Query(None, description="조회 기준 날짜 (YYYY-MM-DD, 기본: 오늘)"),
    user: dict = Depends(verify_firebase_token),
):
    service = ReportService()
    return await service.get_weekly(profile_id, date)
