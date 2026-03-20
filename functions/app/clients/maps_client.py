import httpx
from typing import List
from app.models.common import LatLng
from app.models.route import RouteOptions
from app.config import get_settings


class MapsClient:
    """Google Routes API 클라이언트"""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.google_maps_api_key
        self.routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        self.autocomplete_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        self.directions_url = "https://maps.googleapis.com/maps/api/directions/json"

    async def get_place_details(self, place_id: str) -> dict:
        """Google Places API Details 호출"""
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "language": "ko",
            "fields": "name,formatted_address,geometry"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(self.details_url, params=params)
            if response.status_code != 200:
                print(f"Error from Places Details API: {response.text}")
                return {}
            
            data = response.json().get("result", {})
            if not data:
                return {}
            
            return {
                "place_id": place_id,
                "name": data.get("name"),
                "formatted_address": data.get("formatted_address"),
                "lat": data["geometry"]["location"]["lat"],
                "lng": data["geometry"]["location"]["lng"]
            }
    async def autocomplete(self, input_text: str) -> List[dict]:
        """Google Places API Autocomplete 호출"""
        params = {
            "input": input_text,
            "key": self.api_key,
            "language": "ko",
            "region": "kr", # 한국 지역 우선
            "types": "establishment|geocode" # 장소 및 지명 검색
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(self.autocomplete_url, params=params)
            if response.status_code != 200:
                print(f"Error from Autocomplete API: {response.text}")
                return []
            
            data = response.json()
            predictions = []
            for pred in data.get("predictions", []):
                predictions.append({
                    "description": pred["description"],
                    "place_id": pred["place_id"],
                    "main_text": pred["structured_formatting"]["main_text"],
                    "secondary_text": pred["structured_formatting"].get("secondary_text")
                })
            return predictions

    async def get_candidate_routes(self, origin: LatLng, destination: LatLng, options: RouteOptions) -> List[dict]:
        """Google Routes API(v2) 또는 Directions API(v1)를 호출하여 후보 경로 반환"""
        
        # 1. TRANSIT 모드인 경우 레거시Directions API(v1) 사용 (v2는 아직 미지원)
        if options.travelMode.value if hasattr(options.travelMode, 'value') else options.travelMode == "TRANSIT":
            return await self._get_transit_routes_v1(origin, destination, options)
            
        # 2. 그 외 모드(WALK, BICYCLE, DRIVE 등)는 최신 Routes API(v2) 사용
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs.steps"
        }

        # Routes API 기본 요청 본문
        payload = {
            "origin": {
                "location": {
                    "latLng": {"latitude": origin.lat, "longitude": origin.lng}
                }
            },
            "destination": {
                "location": {
                    "latLng": {"latitude": destination.lat, "longitude": destination.lng}
                }
            },
            "travelMode": options.travelMode.value if hasattr(options.travelMode, 'value') else options.travelMode,
            "computeAlternativeRoutes": True, 
            "languageCode": "ko-KR",
            "units": "METRIC"
        }

        # WALK나 BICYCLE은 routingPreference를 지원하지 않음
        if payload["travelMode"] not in ["WALK", "BICYCLE"]:
            payload["routingPreference"] = "TRAFFIC_AWARE"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.routes_url, 
                json=payload, 
                headers=headers,
                timeout=60.0
            )
            data = response.json()
            
            # v2 결과가 없거나 실패한 경우 도보/자전거면 v1으로 한 번 더 시도
            if (response.status_code != 200 or not data.get("routes")) and payload["travelMode"] in ["WALK", "BICYCLE"]:
                print(f"Routes API v2 returned no results for {payload['travelMode']}. Falling back to v1.")
                return await self._get_routes_v1(origin, destination, options)
            
            if response.status_code != 200:
                print(f"Error from Routes API: {response.text}")
                return []
            
            print(f"Routes API payload: {payload}")
            print(f"Routes API response: {data}")
            routes = []
            for r in data.get("routes", []):
                # v2 포맷은 이미 split_route_into_segments에 맞춰져 있음
                routes.append({
                    "polyline": r["polyline"]["encodedPolyline"],
                    "totalDistance": r["distanceMeters"],
                    "totalDuration": int(float(r["duration"].replace("s", ""))),
                    "raw_steps": r["legs"][0]["steps"],
                    "version": "v2"
                })
            return routes

    async def _get_routes_v1(self, origin: LatLng, destination: LatLng, options: RouteOptions) -> List[dict]:
        """Legacy Directions API (v1) 호출하여 경로 반환"""
        mode_map = {
            "WALK": "walking",
            "BICYCLE": "bicycling",
            "TRANSIT": "transit",
            "DRIVE": "driving"
        }
        requested_mode = options.travelMode.value if hasattr(options.travelMode, 'value') else options.travelMode
        v1_mode = mode_map.get(requested_mode, "walking")

        params = {
            "origin": f"{origin.lat},{origin.lng}",
            "destination": f"{destination.lat},{destination.lng}",
            "mode": v1_mode,
            "alternatives": "true",
            "language": "ko",
            "key": self.api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(self.directions_url, params=params, timeout=60.0)
            if response.status_code != 200:
                print(f"Error from Directions API v1: {response.text}")
                return []
            
            data = response.json()
            if data.get("status") != "OK":
                print(f"Directions API v1 status: {data.get('status')}. Info: {data.get('error_message')}")
                return []
                
            routes = []
            for r in data.get("routes", []):
                leg = r["legs"][0]
                # v2 포맷과 호환되도록 데이터 정규화
                routes.append({
                    "polyline": r["overview_polyline"]["points"],
                    "totalDistance": leg["distance"]["value"],
                    "totalDuration": leg["duration"]["value"],
                    "raw_steps": leg["steps"],
                    "version": "v1" # 버전 정보 기록
                })
            return routes

    async def _get_transit_routes_v1(self, origin: LatLng, destination: LatLng, options: RouteOptions) -> List[dict]:
        """Directions API v1 TRANSIT 전용 호출 (transit_details 포함 응답 처리)"""
        import time as _time

        params = {
            "origin": f"{origin.lat},{origin.lng}",
            "destination": f"{destination.lat},{destination.lng}",
            "mode": "transit",
            "alternatives": "true",
            "language": "ko",
            "departure_time": str(int(_time.time())),  # 현재 시각 기준
            "key": self.api_key
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(self.directions_url, params=params, timeout=60.0)
            if response.status_code != 200:
                print(f"Error from Directions API v1 (transit): {response.text}")
                return []

            data = response.json()
            if data.get("status") != "OK":
                print(f"Directions API v1 transit status: {data.get('status')}. Info: {data.get('error_message')}")
                return []

            routes = []
            for r in data.get("routes", []):
                leg = r["legs"][0]
                routes.append({
                    "polyline": r["overview_polyline"]["points"],
                    "totalDistance": leg["distance"]["value"],
                    "totalDuration": leg["duration"]["value"],
                    "raw_steps": leg["steps"],
                    "version": "v1_transit"  # transit 전용 버전 태그
                })
            return routes

    def split_route_into_segments(self, raw_route: dict) -> List[dict]:
        """경로 단계를 기반으로 세그먼트로 변환 (v1/v2/v1_transit 공통 처리)"""
        segments = []
        version = raw_route.get("version", "v2")
        is_v1 = version in ("v1", "v1_transit")
        is_transit = version == "v1_transit"
        
        for step in raw_route["raw_steps"]:
            if is_v1:
                # Directions API v1 포맷 처리
                start_lat = step["start_location"]["lat"]
                start_lng = step["start_location"]["lng"]
                end_lat = step["end_location"]["lat"]
                end_lng = step["end_location"]["lng"]
                distance = step["distance"]["value"]
                duration = step["duration"]["value"]
                
                # Transit 전용: transit_details에서 풍부한 안내 문구 생성
                if is_transit and "transit_details" in step:
                    instruction = self._build_transit_instruction(step)
                else:
                    instruction = step.get("html_instructions", "")
            else:
                # Routes API v2 포맷 처리
                start_loc = step["startLocation"]["latLng"]
                end_loc = step["endLocation"]["latLng"]
                start_lat, start_lng = start_loc["latitude"], start_loc["longitude"]
                end_lat, end_lng = end_loc["latitude"], end_loc["longitude"]
                distance = step["distanceMeters"]
                duration_str = step.get("duration") or step.get("staticDuration") or "0s"
                duration = int(float(duration_str.replace("s", "")))
                instruction = step.get("navigationInstruction", {}).get("instructions", "")
            
            segments.append({
                "startLatLng": LatLng(lat=start_lat, lng=start_lng),
                "endLatLng": LatLng(lat=end_lat, lng=end_lng),
                "distance": distance,
                "duration": duration,
                "instruction": instruction
            })
            
        return segments

    def _build_transit_instruction(self, step: dict) -> str:
        """transit_details로부터 사용자 친화적인 안내 문구 생성"""
        td = step["transit_details"]
        line = td.get("line", {})
        line_name = line.get("short_name") or line.get("name", "")
        vehicle_type = line.get("vehicle", {}).get("name", "대중교통")
        
        dep_stop = td.get("departure_stop", {}).get("name", "")
        arr_stop = td.get("arrival_stop", {}).get("name", "")
        num_stops = td.get("num_stops", 0)
        
        if line_name and dep_stop and arr_stop:
            return f"{vehicle_type} {line_name} 탑승: {dep_stop} → {arr_stop} ({num_stops}정거장)"
        
        return step.get("html_instructions", "")
