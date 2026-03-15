import os
import asyncio
import functions_framework
from datetime import datetime, timedelta
from google.cloud import firestore
from dotenv import load_dotenv
from collector.clients.air_quality_client import AirQualityClient
from collector.clients.pollen_client import PollenClient
from collector.grid import GridManager

# 환경 변수 로드
load_dotenv()

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")
COLLECTION_NAME = os.environ.get("FIRESTORE_ENV_COLLECTION", "env")
DB = firestore.AsyncClient(project=PROJECT_ID, database=DATABASE_ID)

aq_client = AirQualityClient(API_KEY)
pollen_client = PollenClient(API_KEY)


@functions_framework.http
def collect_environment_data(request):
    """Cloud Scheduler에 의해 5분마다 호출되는 데이터 수집기"""
    
    #  asyncio 이벤트 루프 실행
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_collection())
    finally:
        loop.close()
        
    return "Data collection completed", 200


async def run_collection():
    # 1. 수집할 격자 좌표 가져오기 (비용 효율을 위해 이제 백그라운드에서 모든 격자를 돌리지 않음)
    # 데이터는 사용자가 요청할 때 캐시 사이드 방식으로 실시간 수집됩니다 (EnvironmentService._fetch_and_cache)
    print("Background fixed-grid collection is disabled. Transitioned to On-Demand caching.")
    return
    
    # legacy: grids = GridManager.get_seoul_grids(precision=0.01)[:5]
    
    print(f"Starting collection for {len(grids)} grid points at {datetime.utcnow()}")

    # 2. 격자별 데이터 수집 (병렬 처리)
    # 실제 운영 시에는 Rate Limit를 고려하여 세마포어나 배치를 사용해야 함
    tasks = []
    for lat, lng in grids:
        tasks.append(process_grid(lat, lng))
    
    await asyncio.gather(*tasks)


async def process_grid(lat: float, lng: float):
    """개별 격자 데이터 수집 및 Firestore 저장"""
    grid_id = GridManager.lat_lng_to_grid_id(lat, lng)
    cache_ref = DB.collection(COLLECTION_NAME).document(grid_id)

    try:
        # AQI 및 꽃가루 데이터 병렬 호출
        aq_data, pollen_data = await asyncio.gather(
            aq_client.get_current_conditions(lat, lng),
            pollen_client.get_forecast(lat, lng)
        )

        # Pollen 가공 (방어적 파싱)
        pollen_level = 0
        if pollen_data.get("dailyInfo") and pollen_data["dailyInfo"][0].get("pollenTypeInfo"):
            info = pollen_data["dailyInfo"][0]["pollenTypeInfo"][0]
            if "indexInfo" in info:
                pollen_level = info["indexInfo"]["value"]

        processed_data = {
            "gridId": grid_id,
            "center": {"lat": lat, "lng": lng},
            "timestamp": datetime.utcnow(),
            "expiresAt": datetime.utcnow() + timedelta(minutes=15), # 15분 후 만료
            
            # Air Quality 가공
            "aqi": aq_data["indexes"][0]["aqi"],
            "pm25": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm25"), 0),
            "pm10": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "pm10"), 0),
            "no2": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "no2"), 0),
            "o3": next((p["concentration"]["value"] for p in aq_data.get("pollutants", []) if p["code"] == "o3"), 0),
            
            # Pollen 가공
            "pollenLevel": pollen_level,
            
            # 지표 데이터 가공 (추후 기상 API 및 GIS 연동 필요)
            "temperature": 0.0,
            "feelsLike": 0.0,
            "humidity": 0,
            "shadeRatio": 0.0, 
            "slope": 0.0
        }

        # Firestore 저장
        await cache_ref.set(processed_data)
        
    except Exception as e:
        print(f"Error collecting data for grid {grid_id}: {e}")


if __name__ == "__main__":
    asyncio.run(run_collection())
