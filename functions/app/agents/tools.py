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
async def get_candidate_routes(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, travel_mode: str = "TRANSIT") -> List[Dict[str, Any]]:
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
async def update_user_profile(
    user_id: str, 
    conditions_update: Optional[Dict[str, Any]] = None,
    display_name: Optional[str] = None,
    age: Optional[int] = None
) -> str:
    """Update the user's profile information (name, age, or health conditions).
    - conditions_update: Dict with health fields to update (respiratory, cardiovascular, heatVulnerable, allergyPollen).
    - display_name: The user's name or preferred display name.
    - age: The user's age (1-150).
    Example: update_user_profile(user_id="...", display_name="John", age=30)"""
    service = ProfileService()
    try:
        from app.models.profile import ProfileUpdateRequest, HealthConditions, CustomWeights
        profile = await service.get_by_user_id(user_id)
        if not profile:
            return "Profile not found. Please create a profile first."
        
        update_data = {}
        if display_name:
            update_data["displayName"] = display_name
        if age:
            update_data["age"] = age
            
        if conditions_update:
            # Merge updates with existing conditions
            existing_conditions_dict = profile.conditions.model_dump()
            for key, value in conditions_update.items():
                if key in existing_conditions_dict:
                    if isinstance(value, dict):
                        existing_conditions_dict[key].update(value)
                    elif isinstance(value, str):
                        # Simple string update (e.g. {"respiratory": "high"})
                        existing_conditions_dict[key]["severity"] = value
                        existing_conditions_dict[key]["enabled"] = True
                    elif isinstance(value, bool):
                        # Simple boolean update (e.g. {"respiratory": true})
                        existing_conditions_dict[key]["enabled"] = value
            
            new_conditions = HealthConditions(**existing_conditions_dict)
            update_data["conditions"] = new_conditions
            
            # CRITICAL: Recalculate weights to keep them in sync with new conditions
            from app.services.risk_scorer import RiskScorer
            new_weights_dict = RiskScorer.resolve_weights(new_conditions)
            update_data["customWeights"] = CustomWeights(**new_weights_dict)
        
        update_req = ProfileUpdateRequest(**update_data)
        result = await service.update(profile.profile_id, user_id, update_req)
        
        if result:
            fields = []
            if display_name:
                fields.append("name")
            if age:
                fields.append("age")
            if conditions_update:
                fields.append("health conditions")
            return f"User profile updated successfully. Updated fields: {', '.join(fields)}"
        
        return "Process error: Permission denied for profile update."
    except Exception as e:
        logger.error(f"Error in update_user_profile tool: {e}", exc_info=True)
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
async def compare_routes(user_id: str, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, travel_mode: str = "TRANSIT") -> Dict[str, Any]:
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
