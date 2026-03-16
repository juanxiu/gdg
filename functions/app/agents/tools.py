from langchain_core.tools import tool
from typing import List, Dict, Any
from app.clients.maps_client import MapsClient
from app.services.environment_service import EnvironmentService
from app.services.risk_scorer import RiskScorer
from app.services.profile_service import ProfileService
from app.models.common import LatLng, TravelMode
from app.models.route import RouteOptions
import logging

logger = logging.getLogger("uvicorn")

@tool
async def get_candidate_routes(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, travel_mode: str = "WALK") -> List[Dict[str, Any]]:
    """Google Maps를 사용하여 두 지점 사이의 후보 경로를 검색합니다. 
    travel_mode는 'WALK', 'BICYCLE', 'TRANSIT', 'DRIVE' 중 하나여야 합니다."""
    client = MapsClient()
    options = RouteOptions(travelMode=TravelMode(travel_mode))
    try:
        routes = await client.get_candidate_routes(
            LatLng(lat=origin_lat, lng=origin_lng),
            LatLng(lat=dest_lat, lng=dest_lng),
            options
        )
        # 에이전트가 처리하기 쉽게 세그먼트 정보도 포함하여 반환
        results = []
        for r in routes:
            segments = client.split_route_into_segments(r)
            results.append({
                "polyline": r["polyline"],
                "totalDistance": r["totalDistance"],
                "totalDuration": r["totalDuration"],
                "segments": segments
            })
        return results
    except Exception as e:
        logger.error(f"Error in get_candidate_routes tool: {e}")
        return []

@tool
async def get_environmental_data(locations: List[Dict[str, float]]) -> Dict[str, Any]:
    """지정된 위치들의 미세먼지(AQI), 꽃가루 농도 등 환경 데이터를 조회합니다.
    입력은 [{'lat': 37.5, 'lng': 127.0}, ...] 형식의 리스트입니다."""
    service = EnvironmentService()
    try:
        latlngs = [LatLng(lat=loc['lat'], lng=loc['lng']) for loc in locations]
        return await service.get_for_locations_batch(latlngs)
    except Exception as e:
        logger.error(f"Error in get_environmental_data tool: {e}")
        return {}

@tool
async def get_user_profile(user_id: str) -> Dict[str, Any]:
    """사용자의 건강 프로필(천식, 비염 여부 등)을 조회합니다. user_id만 있으면 자동으로 프로필을 찾습니다."""
    service = ProfileService()
    profile = await service.get_by_user_id(user_id)
    if profile:
        return profile.model_dump()
    return {}

@tool
async def update_user_profile(user_id: str, conditions_update: Dict[str, Any]) -> str:
    """사용자의 건강 프로필 정보를 업데이트합니다. 
    conditions_update는 {'respiratory': {'enabled': True, 'severity': 'high'}, 'allergyPollen': {'enabled': True}} 등의 형식입니다."""
    service = ProfileService()
    try:
        from app.models.profile import ProfileUpdateRequest
        # user_id로 프로필 조회 후 해당 profile_id로 업데이트
        profile = await service.get_by_user_id(user_id)
        if not profile:
            return "프로필을 찾을 수 없습니다. 먼저 프로필을 생성해주세요."
        update_req = ProfileUpdateRequest(conditions=conditions_update)
        result = await service.update(profile.profile_id, user_id, update_req)
        if result:
            return "사용자 프로필이 성공적으로 업데이트되었습니다."
        return "프로세스 오류: 프로필 업데이트 권한이 없습니다."
    except Exception as e:
        logger.error(f"Error in update_user_profile tool: {e}")
        return f"업데이트 실패: {str(e)}"

@tool
def calculate_safety_score(environment_data: Dict[str, Any], profile_conditions: List[str]) -> Dict[str, Any]:
    """환경 데이터와 사용자의 건강 조건을 바탕으로 해당 지점의 위험 점수(0~100)와 등급을 계산합니다."""
    scorer = RiskScorer()
    weights = scorer.resolve_weights(profile_conditions, {})
    
    # 환경 데이터가 dict 형태이므로 SegmentEnvironment 모델로 변환 시도
    from app.models.route import SegmentEnvironment
    try:
        env = SegmentEnvironment(**environment_data)
        score = scorer.calculate_segment_risk(env, weights)
        level = scorer.classify_risk(score)
        return {"score": score, "level": level.value}
    except Exception as e:
        logger.error(f"Error in calculate_safety_score tool: {e}")
        return {"score": 0, "level": "UNKNOWN"}

@tool
async def compare_routes(user_id: str, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, travel_mode: str = "WALK") -> Dict[str, Any]:
    """출발지와 도착지 사이의 최단 경로와 안전 경로를 비교 분석합니다.
    거리, 시간, 건강 위험 점수 차이를 포함한 비교 결과를 반환합니다."""
    from app.services.route_service import RouteService
    from app.models.route import CompareRequest
    
    try:
        service = RouteService()
        profile_service = ProfileService()
        
        # user_id로 프로필 조회
        profile = await profile_service.get_by_user_id(user_id)
        if not profile:
            return {"error": "프로필을 찾을 수 없습니다. 먼저 프로필을 생성해주세요."}
        
        request = CompareRequest(
            origin=LatLng(lat=origin_lat, lng=origin_lng),
            destination=LatLng(lat=dest_lat, lng=dest_lng),
            profile_id=profile.profile_id,
        )
        
        result = await service.compare_routes(request, user_id)
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in compare_routes tool: {e}")
        return {"error": str(e)}
