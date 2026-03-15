import httpx
import polyline
import uuid
from typing import List, Dict
from app.models.common import LatLng
from app.models.route import RouteOptions, TravelMode
from app.config import get_settings


class MapsClient:
    """Google Routes API 클라이언트"""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.google_maps_api_key
        self.routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        self.autocomplete_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.details_url = "https://maps.googleapis.com/maps/api/place/details/json"

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
        """Google Routes API 호출하여 후보 경로 반환"""
        
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
            response = await client.post(self.routes_url, json=payload, headers=headers)
            if response.status_code != 200:
                print(f"Error from Routes API: {response.text}")
                return []
            
            data = response.json()
            print(f"Routes API payload: {payload}")
            print(f"Routes API response: {data}")
            routes = []
            for r in data.get("routes", []):
                routes.append({
                    "polyline": r["polyline"]["encodedPolyline"],
                    "totalDistance": r["distanceMeters"],
                    "totalDuration": int(r["duration"].replace("s", "")),
                    "raw_steps": r["legs"][0]["steps"]
                })
            return routes

    def split_route_into_segments(self, raw_route: dict) -> List[dict]:
        """경로 단계를 기반으로 100m~수백m 단위의 세그먼트로 변환"""
        segments = []
        for step in raw_route["raw_steps"]:
            # 각 Step 자체가 하나의 세그먼트가 됨 (Google이 이미 논리적 단위로 나눠줌)
            start_loc = step["startLocation"]["latLng"]
            end_loc = step["endLocation"]["latLng"]
            
            segments.append({
                "startLatLng": LatLng(lat=start_loc["latitude"], lng=start_loc["longitude"]),
                "endLatLng": LatLng(lat=end_loc["latitude"], lng=end_loc["longitude"]),
                "distance": step["distanceMeters"],
                "duration": int(step["duration"].replace("s", "")),
                "instruction": step.get("navigationInstruction", {}).get("instructions", "")
            })
            
        return segments
