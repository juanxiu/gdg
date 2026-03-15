from typing import Dict
import httpx


class AirQualityClient:
    """Google Air Quality API 클라이언트 (Pipeline 전용)"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://airquality.googleapis.com/v1/currentConditions:lookup"

    async def get_current_conditions(self, lat: float, lng: float) -> Dict:
        """특정 좌표의 대기질 데이터 조회"""
        payload = {
            "location": {"latitude": lat, "longitude": lng},
            "universalAqi": True,
            "extraComputations": [
                "HEALTH_RECOMMENDATIONS",
                "POLLUTANT_CONCENTRATION",
                "LOCAL_AQI"
            ],
            "languageCode": "ko"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.url}?key={self.api_key}",
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
