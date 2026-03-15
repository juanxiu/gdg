from datetime import datetime, time as dt_time
from typing import Optional, List
from app.models.report import WeeklyReportResponse, WeeklyReportSummary, ExposureSummary, TripSummary
from app.db.firestore import get_collection


class ReportService:
    """건강 경로 리포트 서비스"""

    def __init__(self):
        self.collection = get_collection("trips")

    async def get_weekly(self, profile_id: str, date_str: str = None) -> WeeklyReportResponse:
        """한 주 동안의 트립 데이터를 조회하여 요약 리포트 생성"""
        target_date = date_str or datetime.utcnow().date().isoformat()
        
        # 주 단위 범위 설정 (최근 7일)
        end_date = datetime.fromisoformat(target_date)
        end_of_period = datetime.combine(end_date, dt_time.max)
        from datetime import timedelta
        start_date = end_date - timedelta(days=6)
        start_of_period = datetime.combine(start_date, dt_time.min)

        period_str = f"{start_date.date().isoformat()} ~ {end_date.date().isoformat()}"

        # Firestore 쿼리
        query = self.collection.where("profileId", "==", profile_id) \
                               .where("startTime", ">=", start_of_period) \
                               .where("startTime", "<=", end_of_period)
        
        docs = await query.get()
        trips_list = []
        total_dist = 0
        total_dur = 0
        risk_sum = 0
        
        for doc in docs:
            data = doc.to_dict()
            trips_list.append(TripSummary(
                tripId=doc.id,
                startTime=data["startTime"].isoformat(),
                endTime=data["endTime"].isoformat(),
                origin=data.get("originName", ""),
                destination=data.get("destinationName", ""),
                distance=data["distance"],
                duration=data["duration"],
                healthRiskScore=data["healthRiskScore"]
            ))
            total_dist += data["distance"]
            total_dur += data["duration"]
            risk_sum += data["healthRiskScore"]

        is_initial = len(trips_list) == 0
        avg_risk = int(risk_sum / len(trips_list)) if not is_initial else 0

        return WeeklyReportResponse(
            period=period_str,
            profileId=profile_id,
            summary=WeeklyReportSummary(
                totalTrips=len(trips_list),
                totalDistance=total_dist,
                totalDuration=total_dur,
                avgHealthRiskScore=avg_risk,
                hazardsAvoided=len([t for t in trips_list if t.healthRiskScore < 20]),
                healthMinutesSaved=0
            ),
            exposureSummary=ExposureSummary(
                avgPm25=0.0, maxPm25=0.0, avgTemperature=0.0, maxFeelsLike=0.0,
                totalPollenExposure="", avgShadeRatio=0.0
            ),
            trips=trips_list,
            recommendation="최근 활동 데이터가 없습니다. 오늘 첫 산책을 시작해보세요!" if is_initial else "",
            isInitialUser=is_initial
        )

    # export 메서드 삭제 예정이나 router에서만 막아도 됨. 일단 둠.
