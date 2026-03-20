from datetime import datetime, timedelta
from typing import List, Dict
from app.models.common import LatLng
from app.models.environment import (
    CurrentEnvironmentResponse, AirQualityData, WeatherData, 
    PollenData, PollenTypeDetail, HealthAdvisory, 
    EnvironmentAreaResponse, EnvironmentalDataType, EnvironmentAreaInfo
)
from app.config import get_settings
from app.db.firestore import get_collection
from app.utils.grid import GridManager
from app.clients.air_quality_client import AirQualityClient
from app.clients.pollen_client import PollenClient
import asyncio
from google.cloud import firestore


class EnvironmentService:
    """환경 데이터 조회 및 캐시 관리 서비스"""

    def __init__(self):
        self.settings = get_settings()
        self.collection = get_collection(self.settings.firestore_env_collection)
        self.aq_client = AirQualityClient(self.settings.google_maps_api_key)
        self.pollen_client = PollenClient(self.settings.google_maps_api_key)
        self.semaphore = asyncio.Semaphore(10) # 최대 10개 병렬 호출 제한

    async def get_for_location(self, location: LatLng):
        """특정 좌표의 실시간 환경 데이터 조회 (Cache-Aside 전략)"""
        results = await self.get_for_locations_batch([location])
        grid_id = GridManager.lat_lng_to_grid_id(location.lat, location.lng)
        return results.get(grid_id) if results else None

    async def get_for_locations_batch(self, locations: List[LatLng]) -> Dict[str, dict]:
        """여러 좌표의 실시간 환경 데이터를 배치로 조회"""
        grid_map = {}
        for loc in locations:
            grid_id = GridManager.lat_lng_to_grid_id(loc.lat, loc.lng)
            if grid_id not in grid_map:
                grid_map[grid_id] = loc

        grid_ids = list(grid_map.keys())
        print(f"[DEBUG] EnvironmentService: {len(locations)} locations mapped to {len(grid_ids)} unique grids")
        if not grid_ids:
            return {}

        from app.db.firestore import get_db
        db = get_db()
        doc_refs = [self.collection.document(gid) for gid in grid_ids]

        # Firestore 배치 조회 (Async Generator 처리)
        docs = []
        async for doc in db.get_all(doc_refs):
            docs.append(doc)
        
        results = {}
        fetch_tasks = []
        now = datetime.utcnow().replace(tzinfo=None)
        
        for doc in docs:
            data = None
            if doc.exists:
                doc_data = doc.to_dict()
                updated_at = doc_data.get("updatedAt")
                # updated_at은 Firestore Timestamp일 수 있음 (가끔 datetime으로 자동 변환되기도 함)
                if updated_at:
                    if hasattr(updated_at, "replace"):
                         updated_at_dt = updated_at.replace(tzinfo=None)
                    else: # Timestamp object
                         updated_at_dt = updated_at.to_datetime().replace(tzinfo=None)
                         
                    if (now - updated_at_dt) < timedelta(hours=1):
                        data = doc_data
            
            grid_id = doc.id
            if data:
                results[grid_id] = data
            else:
                loc = grid_map[grid_id]
                fetch_tasks.append(self._fetch_and_cache(loc.lat, loc.lng, grid_id))

        if fetch_tasks:
            print(f"[DEBUG] EnvironmentService: Fetching real-time data for {len(fetch_tasks)} grids")
            # 실시간 API 호출 병렬 수행
            fetched_results = await asyncio.gather(*fetch_tasks)
            for fr in fetched_results:
                results[fr["gridId"]] = fr
                
        return results

    async def _fetch_and_cache(self, lat: float, lng: float, grid_id: str):
        """실시간 API 호출 및 Firestore 저장"""
        async with self.semaphore:
            try:
                # 병렬 호출
                aq_task = self.aq_client.get_current_conditions(lat, lng)
                pollen_task = self.pollen_client.get_forecast(lat, lng)
                aq_data, pollen_data = await asyncio.gather(aq_task, pollen_task)

                # 데이터 가공 (안전하게 인덱스 확인)
                pollen_level = 0
                if pollen_data.get("dailyInfo") and pollen_data["dailyInfo"][0].get("pollenTypeInfo"):
                    info = pollen_data["dailyInfo"][0]["pollenTypeInfo"][0]
                    if "indexInfo" in info:
                        pollen_level = info["indexInfo"].get("value", 0)

                # AQI 데이터 안전 파싱 (IndexError 방지)
                aqi_val = 0
                if aq_data.get("indexes") and len(aq_data["indexes"]) > 0:
                    aqi_val = aq_data["indexes"][0].get("aqi", 0)

                processed_data = {
                    "gridId": grid_id,
                    "lat": lat,
                    "lng": lng,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                    "aqi": aqi_val,
                    "pm25": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm25"), 0),
                    "pm10": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm10"), 0),
                    "no2": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "no2"), 0),
                    "o3": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "o3"), 0),
                    "pollenLevel": pollen_level,
                    "temperature": 0.0,
                    "feelsLike": 0.0,
                    "humidity": 0,
                    "shadeRatio": 0.0
                }

                # Firestore 저장
                await self.collection.document(grid_id).set(processed_data)
                return processed_data
                
            except Exception as e:
                # API 에러 시 기본값 반환 (로그 남기기 필요)
                print(f"Error fetching real-time data: {e}")
                return {
                    "gridId": grid_id,
                    "lat": lat,
                    "lng": lng,
                    "aqi": 0, "pm25": 0.0, "pm10": 0.0, "no2": 0.0, "o3": 0.0,
                    "pollenLevel": 0, "temperature": 20.0, "feelsLike": 20.0,
                    "humidity": 50, "shadeRatio": 0.0, "slope": 0.0
                }

    async def get_current(self, lat: float, lng: float) -> CurrentEnvironmentResponse:
        """현재 위치의 환경 상세 정보 (API 엔드포인트용)"""
        data = await self.get_for_location(LatLng(lat=lat, lng=lng))
        if not data:
            # 데이터가 없는 경우 기본값 반환 (서버 오류 방지)
            data = {
                "aqi": 0, "pm25": 0.0, "pm10": 0.0, "no2": 0.0, "o3": 0.0,
                "pollenLevel": 0, "temperature": 20.0, "feelsLike": 20.0,
                "humidity": 50, "pollenTypes": []
            }

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
