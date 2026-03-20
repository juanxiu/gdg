import uuid
import time
from fastapi import HTTPException, status
from app.models.common import LatLng, RiskLevel, HazardType, TravelMode
from app.models.route import (
    SafeRouteRequest, SafeRouteResponse, SafePathResult,
    RouteSegment, RouteMetadata, SegmentEnvironment,
    CompareRequest, CompareResponse, RerouteRequest, RerouteResponse,
    LocationUpdateRequest, LocationUpdateResponse, AheadScan, AheadHazard
)
from app.services.risk_scorer import RiskScorer
from app.services.profile_service import ProfileService
from app.services.environment_service import EnvironmentService
from app.agents.agent import get_agent
from app.clients.maps_client import MapsClient
from app.utils.grid import GridManager
from app.config import get_settings
from app.db.firestore import get_collection


import math
class RouteService:
    """SafePath 경로 탐색 및 관리 서비스"""

    def __init__(self):
        self.profile_service = ProfileService()
        self.env_service = EnvironmentService()
        self.maps_client = MapsClient()
        self.risk_scorer = RiskScorer()
        self.agent = get_agent()
        self.settings = get_settings()
        self.db = get_collection("routes") # 경로 저장용 컬렉션

    async def find_safe_route(self, request: SafeRouteRequest, user_id: str) -> SafeRouteResponse:
        start_time = time.time()

        # 1. 프로필 조회 (userId를 넘겨 소유권 확인)
        profile = await self.profile_service.get(request.profile_id, user_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {request.profile_id} not found or access denied"
            )

        # 2. 가중치 결정
        weights = self.risk_scorer.resolve_weights(profile.conditions, profile.customWeights)

        # 3. Google Routes API로 후보 경로 조회
        # (실제 구현 시 maps_client가 다중 경로를 반환하도록 함)
        candidate_routes = await self.maps_client.get_candidate_routes(
            request.origin, request.destination, request.options
        )

        # 4. 모든 후보 경로의 세그먼트 좌표 미리 추출 (배치 처리를 위함)
        all_segments_by_route = []
        all_locations = []
        for raw_route in candidate_routes:
            segments_data = self.maps_client.split_route_into_segments(raw_route)
            all_segments_by_route.append(segments_data)
            for seg in segments_data:
                all_locations.append(seg["startLatLng"])

        # 5. 환경 데이터 한 번에 조회 (Batch)
        env_results = await self.env_service.get_for_locations_batch(all_locations)

        # 6. 세그먼트별 리스크 점수 계산 및 경로 구성
        scored_paths = []
        for i, raw_route in enumerate(candidate_routes):
            segments_data = all_segments_by_route[i]
            path_segments = []
            total_risk = 0
            
            for seg in segments_data:
                start_latlng = LatLng.model_validate(seg["startLatLng"])
                grid_id = GridManager.lat_lng_to_grid_id(start_latlng.lat, start_latlng.lng)
                env_dict = env_results.get(grid_id)
                
                if not env_dict:
                    # 데이터 누락 시 기본값 (env_service에서 보장하지만 방어적 처리)
                    env_dict = {
                        "gridId": grid_id,
                        "lat": start_latlng.lat, "lng": start_latlng.lng,
                        "aqi": 0, "pollenLevel": 0, "temperature": 20.0
                    }
                
                env = SegmentEnvironment(**env_dict)
                
                # Risk Score 계산 (순수 연산이므로 루프 내에서 수행)
                score = self.risk_scorer.calculate_segment_risk(env, weights)
                level = self.risk_scorer.classify_risk(score)
                
                route_seg = RouteSegment(
                    segmentId=str(uuid.uuid4()),
                    startLatLng=seg["startLatLng"],
                    endLatLng=seg["endLatLng"],
                    distance=seg["distance"],
                    duration=seg["duration"],
                    riskScore=score,
                    riskLevel=level,
                    environment=env,
                    instruction=seg["instruction"]
                )
                path_segments.append(route_seg)
                total_risk += score * seg["distance"] # 거리 가중 평균용

            total_distance = raw_route["totalDistance"]
            avg_risk = int(total_risk / total_distance) if total_distance > 0 else 0
            
            scored_paths.append({
                "route": raw_route,
                "segments": path_segments,
                "avgRisk": avg_risk
            })

        if not scored_paths:
            # Provide more helpful feedback for regions where walking/bicycle is not supported (e.g., Korea)
            msg = "No candidate routes found."
            if request.options.travelMode in [TravelMode.WALK, TravelMode.BICYCLE]:
                msg += " Note: Walking/Bicycle directions are not supported in Korea via Google Maps. Please try 'TRANSIT' mode instead."
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg
            )

        # 6. 모든 후보 경로를 Risk Score 순으로 정렬
        scored_paths.sort(key=lambda x: x["avgRisk"])
        
        path_results = []
        for best in scored_paths:
            safe_path = SafePathResult(
                routeId=f"route_{uuid.uuid4().hex[:8]}",
                polyline=best["route"]["polyline"],
                totalDistance=best["route"]["totalDistance"],
                totalDuration=best["route"]["totalDuration"],
                healthRiskScore=best["avgRisk"],
                summary="", # UI에서 처리하도록 비움
                segments=best["segments"],
                warnings=[]
            )
            # 경로 데이터 저장 (네비게이션 연동용)
            await self.db.document(safe_path.routeId).set(safe_path.model_dump())
            path_results.append(safe_path)

        metadata = RouteMetadata(
            profileApplied=profile.displayName,
            weightsUsed=weights,
            dataFreshness="", # 데이터 수집 시각 연동 필요
            computedIn=round(time.time() - start_time, 2)
        )

        return SafeRouteResponse(paths=path_results, metadata=metadata)

    async def compare_routes(self, request: CompareRequest, user_id: str) -> CompareResponse:
        """최단 경로와 SafePath를 직접 비교하여 분석"""
        safe_resp = await self.find_safe_route(SafeRouteRequest(
            origin=request.origin,
            destination=request.destination,
            profile_id=request.profile_id,
            departureTime=request.departureTime,
            options=request.options
        ), user_id)
        
        if not safe_resp.paths:
            raise HTTPException(status_code=404, detail="No paths available for comparison")


        # 1. 안전성 기준 정렬된 결과 (이미 find_safe_route에서 정렬됨)
        safest_path = safe_resp.paths[0]
        
        # 2. 최단 경로(시간 기준) 찾기
        fastest_path = min(safe_resp.paths, key=lambda x: x.totalDuration)
        
        # 3. 차이 계산
        dist_diff = safest_path.totalDistance - fastest_path.totalDistance
        dur_diff = safest_path.totalDuration - fastest_path.totalDuration
        risk_diff = safest_path.healthRiskScore - fastest_path.healthRiskScore # 보통 음수일 것 (안전한게 낮음)

        # 4. Return structured comparison data
        return CompareResponse(
            comparison={
                "safePath": safest_path,
                "fastestPath": fastest_path,
                "delta": {
                    "distanceDiff": dist_diff,
                    "durationDiff": dur_diff,
                    "riskScoreDiff": risk_diff,
                    "recommendation": "Safety prioritized" if risk_diff < 0 else "Fastest route recommended",
                    "reason": f"Safe path reduces risk by {abs(risk_diff)} points but takes {dur_diff}s longer."
                }
            }
        )

    async def reroute(self, request: RerouteRequest, user_id: str) -> RerouteResponse:
        """위험 구역을 우회하는 재탐색 수행"""
        # 1. 기존 경로 정보 조회 (위험도 비교용)
        old_route_doc = await self.db.document(request.currentRouteId).get()
        original_remaining_risk = 0
        
        if old_route_doc.exists:
            old_data = old_route_doc.to_dict()
            # 현재 위치 이후의 세그먼트들만 추출하여 최신 위험도 재계산
            # (단순화를 위해 여기서는 전체 평균 점수 사용 혹은 로직 고도화 가능)
            original_remaining_risk = old_data.get("healthRiskScore", 0)

        # 2. 새로운 SafePath 탐색
        re_resp = await self.find_safe_route(SafeRouteRequest(
            origin=request.currentLocation,
            destination=request.destination,
            profile_id=request.profile_id
        ), user_id)
        
        # 첫 번째 경로가 가장 안전한 경로
        best_new_path = re_resp.paths[0]
        new_risk = best_new_path.healthRiskScore
        improvement = max(0, int(((original_remaining_risk - new_risk) / original_remaining_risk * 100))) if original_remaining_risk > 0 else 0
        
        return RerouteResponse(
            reroutedPath=best_new_path,
            originalRemainingRisk=original_remaining_risk,
            newRisk=new_risk,
            improvement=improvement
        )

    async def process_location_update(self, request: LocationUpdateRequest, user_id: str) -> LocationUpdateResponse:
        """실시간 위치 기반 전방 위험 스캔 및 경로 추적"""
        # 1. 경로 데이터 로드
        route_doc = await self.db.document(request.routeId).get()
        if not route_doc.exists:
            raise HTTPException(status_code=404, detail="Route not found")
        
        route_data = route_doc.to_dict()
        segments = route_data.get("segments", [])
        
        if not segments:
            raise HTTPException(status_code=400, detail="The route has no valid segments.")
        
        # 2. 현재 위치와 가장 가까운 세그먼트 찾기
        curr_idx = 0
        min_dist = float('inf')
        for i, seg in enumerate(segments):
            # 단순 노드 거리 대신 점-대-세그먼트 거리 사용 고려 (고도화)
            d = self._get_point_to_segment_distance(
                request.location, 
                LatLng.model_validate(seg["startLatLng"]), 
                LatLng.model_validate(seg["endLatLng"])
            )
            if d < min_dist:
                min_dist = d
                curr_idx = i
        
        # 3. 남은 거리 및 ETA 계산 (단순화: 남은 세그먼트 합계)
        remaining_segments = segments[curr_idx:]
        rem_dist = sum(s["distance"] for s in remaining_segments)
        rem_dur = sum(s["duration"] for s in remaining_segments)
        
        # 4. 전방 위험 스캔 (다음 5개 세그먼트 약 500m)
        ahead_hazards = []
        hazard_detected = False
        scan_segments = segments[curr_idx + 1: min(curr_idx + 6, len(segments))]
        scan_locations = [LatLng.model_validate(s["startLatLng"]) for s in scan_segments]
        
        # 가중치 획득
        profile = await self.profile_service.get(request.profile_id, user_id)
        weights = self.risk_scorer.resolve_weights(profile.conditions, profile.customWeights) if profile else {}

        # 배치 조회
        env_results = await self.env_service.get_for_locations_batch(scan_locations) if scan_locations else {}
        
        scan_dist = 0
        for seg in scan_segments:
            scan_dist += seg["distance"]
            
            start_latlng = LatLng.model_validate(seg["startLatLng"])
            grid_id = GridManager.lat_lng_to_grid_id(start_latlng.lat, start_latlng.lng)
            env_dict = env_results.get(grid_id)
            
            if not env_dict:
                env_dict = {"gridId": grid_id, "lat": start_latlng.lat, "lng": start_latlng.lng, "aqi": 0, "pollenLevel": 0}
            
            env = SegmentEnvironment(**env_dict)
            
            # 최신 데이터 기반 리스크 재계산
            fresh_score = self.risk_scorer.calculate_segment_risk(env, weights)
            
            if fresh_score >= 50: # WARNING 이상
                hazard_detected = True
                ahead_hazards.append(AheadHazard(
                    type=HazardType.AIR_QUALITY if env_dict.get("aqi", 0) > 100 else HazardType.POLLEN,
                    severity=self.risk_scorer.classify_risk(fresh_score),
                    distanceAhead=scan_dist,
                    location=LatLng.model_validate(seg["startLatLng"])
                ))

        # 5. 위험 감지 시 에이전트 기반 분석
        alert_message = ""
        reroute_recommended = False
        if hazard_detected:
            # 에이전트에게 현재 상황과 유저 프로필을 전달하여 판단 요청
            query = (
                f"현재 내비게이션 중 전방 {scan_dist}m 지점에 위험이 감지되었습니다. "
                f"위험 정보: {[h.model_dump() for h in ahead_hazards]} "
                f"사용자 프로필: {profile.model_dump() if profile else {}} "
                "이 상황이 사용자에게 얼마나 위험한지 판단하고, '메시지: [설명] | 재탐색권장: [True/False]' 형식으로 답해줘."
            )
            agent_response = await self.agent.run(
                user_id=user_id,
                query=query
            )
            
            # 응답 파싱
            if "|" in agent_response:
                parts = agent_response.split("|")
                alert_message = parts[0].replace("메시지:", "").strip()
                reroute_val = parts[1].replace("재탐색권장:", "").strip().lower()
                reroute_recommended = (reroute_val == "true")
            else:
                alert_message = agent_response

        return LocationUpdateResponse(
            status="HAZARD_AHEAD" if hazard_detected else "ON_ROUTE",
            message=alert_message,
            currentSegmentId=segments[curr_idx]["segmentId"],
            nextSegmentRisk=segments[curr_idx+1]["riskLevel"] if curr_idx+1 < len(segments) else RiskLevel.SAFE,
            aheadScan=AheadScan(
                scannedDistance=scan_dist,
                hazardDetected=hazard_detected,
                hazards=ahead_hazards
            ),
            rerouteRecommended=reroute_recommended,
            eta=rem_dur,
            remainingDistance=rem_dist
        )

    def _get_distance(self, p1: LatLng, p2: LatLng) -> float:
        """두 좌표 간의 직선 거리 (m) - 단순 계산"""
        R = 6371000 # 지구 반지름
        phi1, phi2 = math.radians(p1.lat), math.radians(p2.lat)
        dphi = math.radians(p2.lat - p1.lat)
        dlamb = math.radians(p2.lng - p1.lng)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlamb/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _get_point_to_segment_distance(self, p: LatLng, a: LatLng, b: LatLng) -> float:
        """점 P에서 선분 AB까지의 최단 거리 (m)"""
        # 단순 가우스 평면 투영 (짧은 거리에서 유효)
        # 위도 1도는 약 111,000m, 경도 1도는 111,000 * cos(lat) m
        lat0 = math.radians(a.lat)
        kx = 111000 * math.cos(lat0)
        ky = 111000
        
        px, py = p.lng * kx, p.lat * ky
        ax, ay = a.lng * kx, a.lat * ky
        bx, by = b.lng * kx, b.lat * ky
        
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return self._get_distance(p, a)
            
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        
        return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
