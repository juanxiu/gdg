from datetime import datetime, timedelta
from typing import List
from app.models.common import LatLng
from app.models.environment import (
    CurrentEnvironmentResponse, AirQualityData, WeatherData, 
    PollenData, PollenTypeDetail, HealthAdvisory, 
    EnvironmentAreaResponse, EnvironmentalDataType, EnvironmentAreaInfo
)
from app.config import get_settings
from app.db.firestore import get_collection
from app.utils.grid import GridManager
from pipeline.collector.clients.air_quality_client import AirQualityClient
from pipeline.collector.clients.pollen_client import PollenClient
import asyncio
from google.cloud import firestore


class EnvironmentService:
    """환경 데이터 조회 및 캐시 관리 서비스"""

    def __init__(self):
        self.settings = get_settings()
        self.collection = get_collection(self.settings.firestore_env_collection)
        self.aq_client = AirQualityClient(self.settings.google_maps_api_key)
        self.pollen_client = PollenClient(self.settings.google_maps_api_key)

    async def get_for_location(self, location: LatLng):
        """특정 좌표의 실시간 환경 데이터 조회 (Cache-Aside 전략)"""
        grid_id = GridManager.lat_lng_to_grid_id(location.lat, location.lng)
        doc_ref = self.collection.document(grid_id)
        doc = await doc_ref.get()
        
        # 캐시 히트 및 만료 확인 (1시간)
        if doc.exists:
            data = doc.to_dict()
            updated_at = data.get("updatedAt")
            if updated_at:
                # Firestore Timestamp를 datetime으로 변환 (직접 비교 가능)
                if (datetime.utcnow().replace(tzinfo=None) - updated_at.replace(tzinfo=None)) < timedelta(hours=1):
                    return data
        
        # 캐시 미스 또는 만료: 실시간 데이터 호출
        return await self._fetch_and_cache(location.lat, location.lng, grid_id)

    async def _fetch_and_cache(self, lat: float, lng: float, grid_id: str):
        """실시간 API 호출 및 Firestore 저장"""
        try:
            # 병렬 호출
            aq_task = self.aq_client.get_current_conditions(lat, lng)
            pollen_task = self.pollen_client.get_forecast(lat, lng)
            aq_data, pollen_data = await asyncio.gather(aq_task, pollen_task)

            # 데이터 가공 (pipeline/main.py 로직 유지)
            pollen_level = 0
            if pollen_data.get("dailyInfo") and pollen_data["dailyInfo"][0].get("pollenTypeInfo"):
                info = pollen_data["dailyInfo"][0]["pollenTypeInfo"][0]
                if "indexInfo" in info:
                    pollen_level = info["indexInfo"]["value"]

            processed_data = {
                "gridId": grid_id,
                "lat": lat,
                "lng": lng,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "aqi": aq_data["indexes"][0]["aqi"],
                "pm25": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm25"), 0),
                "pm10": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm10"), 0),
                "no2": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "no2"), 0),
                "o3": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "o3"), 0),
                "pollenLevel": pollen_level,
                "temperature": 0.0, # 추후 기상 API 연동
                "feelsLike": 0.0,
                "humidity": 0,
                "shadeRatio": 0.0
            }

            # Firestore 저장 (백그라운드 실행 권장되나 여기서는 동기적 유지)
            await self.collection.document(grid_id).set(processed_data)
            return processed_data
            
        except Exception as e:
            # API 에러 시 기본값 반환 (로그 남기기 필요)
            print(f"Error fetching real-time data: {e}")
            return {
                "aqi": 0, "pm25": 0.0, "pm10": 0.0, "no2": 0.0, "o3": 0.0,
                "pollenLevel": 0, "temperature": 20.0, "expiresAt": None
            }

    async def get_current(self, lat: float, lng: float) -> CurrentEnvironmentResponse:
        """현재 위치의 환경 상세 정보 (API 엔드포인트용)"""
        data = await self.get_for_location(LatLng(lat=lat, lng=lng))
        aqi = data.get("aqi", 0)
        pollen_level = data.get("pollenLevel", 0)
        
        return CurrentEnvironmentResponse(
            location={"lat": lat, "lng": lng},
            timestamp=datetime.utcnow().isoformat(),
            airQuality=AirQualityData(
                aqi=aqi,
                category=self._get_aqi_category(aqi),
                pm25=data.get("pm25", 0.0),
                pm10=data.get("pm10", 0.0),
                no2=data.get("no2", 0.0),
                o3=data.get("o3", 0.0),
                co=0.0,
                so2=0.0,
                dominantPollutant=""
            ),
            weather=WeatherData(
                temperature=data.get("temperature", 0.0),
                feelsLike=data.get("feelsLike", 0.0),
                humidity=data.get("humidity", 0),
                uvIndex=0,
                windSpeed=0.0,
                windDirection=""
            ),
            pollen=PollenData(
                overallLevel=pollen_level,
                overallCategory=self._get_pollen_category(pollen_level),
                types=[PollenTypeDetail(name=t, level=pollen_level) for t in data.get("pollenTypes", [])]
            ),
            healthAdvisory=HealthAdvisory(
                respiratory=""
            )
        )

    def _get_aqi_category(self, aqi: int) -> str:
        if aqi <= 50:
            return "Good"
        elif aqi <= 100:
            return "Moderate"
        elif aqi <= 150:
            return "Unhealthy for Sensitive Groups"
        elif aqi <= 200:
            return "Unhealthy"
        return "Hazardous"

    def _get_pollen_category(self, level: int) -> str:
        if level <= 1:
            return "Low"
        elif level <= 3:
            return "Moderate"
        return "High"

    async def get_area_data(self, swLat: float, swLng: float, neLat: float, neLng: float, zoom: int, data_type: EnvironmentalDataType) -> EnvironmentAreaResponse:
        """지정된 영역의 격자 데이터를 조회하여 반환"""
        # Firestore에서 범위 쿼리를 통해 격자 데이터 조회
        # (로컬 개발용: 단순화를 위해 모든 격자를 가져와 필터링하거나 격자 ID 리스트 생성)
        
        # 1. 수집 정밀도(precision) 결정 (줌 레벨에 따라 조정 가능)
        precision = 0.01  # 현재 데이터 수집기 정밀도(1km)
        
        # 2. 범위 내의 모든 격자 중심점 계산
        areas = []
        curr_lat = round(swLat / precision) * precision
        while curr_lat <= neLat + precision:
            curr_lng = round(swLng / precision) * precision
            while curr_lng <= neLng + precision:
                # 범위 내에 있는지 확인
                if swLat <= curr_lat <= neLat and swLng <= curr_lng <= neLng:
                    grid_id = GridManager.lat_lng_to_grid_id(curr_lat, curr_lng)
                    doc = await self.collection.document(grid_id).get()
                    
                    if doc.exists:
                        data = doc.to_dict()
                        val = data.get(data_type.value, 0.0)
                        
                        # AQI 등의 데이터 타입에 따른 색상/레벨 매핑 (추후 RiskScorer 연동)
                        level = "SAFE"
                        color = "#4CAF50"
                        if data_type == EnvironmentalDataType.AQI:
                            if val > 150:
                                level, color = "DANGER", "#F44336"
                            elif val > 100:
                                level, color = "WARNING", "#FF9800"
                            elif val > 50:
                                level, color = "CAUTION", "#FFEB3B"
                        
                        areas.append(EnvironmentAreaInfo(
                            lat=curr_lat,
                            lng=curr_lng,
                            value=float(val),
                            level=level,
                            color=color
                        ))
                curr_lng += precision
            curr_lat += precision
            
        return EnvironmentAreaResponse(
            type=data_type,
            bounds={"sw": {"lat": swLat, "lng": swLng}, "ne": {"lat": neLat, "lng": neLng}},
            gridSize=int(precision * 111111), # 대략적인 미터 단위
            areas=areas,
            generatedAt=datetime.utcnow().isoformat()
        )
