from langchain_core.tools import tool
from typing import List, Dict, Any, Optional
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
    """Search for candidate routes between two points using Google Maps.
    - travel_mode: Select from 'WALK', 'BICYCLE', 'TRANSIT', 'DRIVE'. Defaults to 'WALK'."""
    client = MapsClient()
    options = RouteOptions(travelMode=TravelMode(travel_mode))
    try:
        routes = await client.get_candidate_routes(
            LatLng(lat=origin_lat, lng=origin_lng),
            LatLng(lat=dest_lat, lng=dest_lng),
            options
        )
        # Return segment information for easier processing by the agent (limited to 50 segments to avoid overload)
        results = []
        for r in routes:
            segments = client.split_route_into_segments(r)
            is_truncated = len(segments) > 50
            results.append({
                "polyline": r["polyline"],
                "totalDistance": r["totalDistance"],
                "totalDuration": r["totalDuration"],
                "segments": segments[:50],
                "is_truncated": is_truncated,
                "message": "Route is too long; only the first 50 segments are returned." if is_truncated else ""
            })
        return results
    except Exception as e:
        logger.error(f"Error in get_candidate_routes tool: {e}")
        return []

@tool
async def get_environmental_data(locations: List[Dict[str, float]]) -> Dict[str, Any]:
    """Retrieve environmental data such as air quality (AQI) and pollen levels for specified locations.
    - locations: A list of dicts like [{'lat': 37.5, 'lng': 127.0}, ...]."""
    service = EnvironmentService()
    try:
        latlngs = [LatLng(lat=loc['lat'], lng=loc['lng']) for loc in locations]
        return await service.get_for_locations_batch(latlngs)
    except Exception as e:
        logger.error(f"Error in get_environmental_data tool: {e}")
        return {}

@tool
async def get_user_profile(user_id: str) -> Dict[str, Any]:
    """Retrieve the user's health profile (respiratory issues, allergies, etc.) using their user_id."""
    service = ProfileService()
    profile = await service.get_by_user_id(user_id)
    if profile:
        return profile.model_dump()
    return {}

@tool
async def update_user_profile(user_id: str, conditions_update: Dict[str, Any]) -> str:
    """Update the user's health profile conditions.
    - conditions_update: A dict containing only the fields to update. Available keys:
        - respiratory: Respiratory diseases (Asthma, COPD, Rhinitis, etc.)
        - cardiovascular: Cardiovascular diseases (Hypertension, Heart disease, etc.)
        - heatVulnerable: Vulnerability to heat (Heatstroke, etc.)
        - allergyPollen: Pollen allergy
    - Format: {"enabled": bool, "severity": "low"|"medium"|"high"}
    Example: {"allergyPollen": {"enabled": True, "severity": "high"}}"""
    service = ProfileService()
    try:
        from app.models.profile import ProfileUpdateRequest
        profile = await service.get_by_user_id(user_id)
        if not profile:
            return "Profile not found. Please create a profile first."
        
        # Merge updates with existing conditions
        existing_conditions = profile.conditions.model_dump()
        for key, value in conditions_update.items():
            if key in existing_conditions:
                existing_conditions[key].update(value)
        
        update_req = ProfileUpdateRequest(conditions=existing_conditions)
        result = await service.update(profile.profile_id, user_id, update_req)
        if result:
            return f"User profile updated successfully. Updated fields: {list(conditions_update.keys())}"
        return "Process error: Permission denied for profile update."
    except Exception as e:
        logger.error(f"Error in update_user_profile tool: {e}")
        return f"Update failed: {str(e)}"

@tool
def calculate_safety_score(environment_data: Dict[str, Any], profile_conditions: List[str]) -> Dict[str, Any]:
    """Calculate the health risk score (0-100) and risk level for a location based on environmental data and user conditions."""
    scorer = RiskScorer()
    weights = scorer.resolve_weights(profile_conditions, {})
    
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
    """Compare the fastest route and the safest route between two points. 
    Returns distance, duration, and health risk score differences."""
    from app.services.route_service import RouteService
    from app.models.route import CompareRequest
    
    try:
        service = RouteService()
        profile_service = ProfileService()
        
        profile = await profile_service.get_by_user_id(user_id)
        if not profile:
            return {"error": "Profile not found. Please create a profile first."}
        
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

@tool
async def search_place(query: str, place_id: Optional[str] = None) -> Dict[str, Any]:
    """Search for a place by name/address or retrieve details for a specific Google Place ID.
    - query: Search string (e.g., 'Gangnam Station')
    - place_id: Specific Google Place ID (if selected from a candidate list)"""
    client = MapsClient()
    try:
        if place_id:
            details = await client.get_place_details(place_id)
            if details:
                return {
                    "type": "SINGLE_RESULT",
                    "name": details.get("name"),
                    "address": details.get("address"),
                    "lat": details.get("lat"),
                    "lng": details.get("lng"),
                    "placeId": place_id
                }
        
        predictions = await client.autocomplete(query)
        if not predictions:
            return {"error": f"No results found for '{query}'."}
        
        if len(predictions) == 1:
            place_id = predictions[0].get("place_id")
            details = await client.get_place_details(place_id)
            if details:
                return {
                    "type": "SINGLE_RESULT",
                    "name": details.get("name"),
                    "address": details.get("address"),
                    "lat": details.get("lat"),
                    "lng": details.get("lng"),
                    "placeId": place_id
                }
        
        return {
            "type": "MULTIPLE_RESULTS",
            "predictions": predictions
        }
    except Exception as e:
        logger.error(f"Error in search_place tool: {e}")
        return {"error": str(e)}
