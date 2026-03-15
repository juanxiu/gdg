from typing import Dict
import httpx


class PollenClient:
    """Google Pollen API 클라이언트"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://pollen.googleapis.com/v1/forecast:lookup"

    async def get_forecast(self, lat: float, lng: float) -> Dict:
        """특정 좌표의 꽃가루 예측 데이터 조회"""
        params = {
            "key": self.api_key,
            "location.latitude": lat,
            "location.longitude": lng,
            "days": 1,
            "languageCode": "ko"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.url,
                params=params,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
