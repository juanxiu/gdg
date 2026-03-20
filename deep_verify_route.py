import sys
import os
import asyncio
from pydantic import BaseModel

# Set up path to include the 'functions' directory
sys.path.append(os.path.join(os.getcwd(), 'functions'))

# Mocking parts to avoid dependency issues if needed, but let's try real ones first
try:
    from app.services.route_service import RouteService
    from app.services.profile_service import ProfileService
    from app.models.route import CompareRequest
    from app.models.common import LatLng
    from app.models.profile import ProfileCreateRequest, HealthConditions
except ImportError:
    print("Dependencies not found, skipping real objects.")
    sys.exit(0)

async def test_full_route_service():
    user_id = "test_user_seoul"
    rs = RouteService()
    ps = ProfileService()
    
    # 1. Ensure profile exists
    print(f"Ensuring profile for {user_id}...")
    profile = await ps.get_by_user_id(user_id)
    print(f"Profile: {profile.displayName if profile else 'None'}")
    
    # 2. Compare routes (Seoul Station to Gwanghwamun)
    # Origin: Seoul Station (37.5546, 126.9706)
    # Destination: Gwanghwamun (37.5759, 126.9768)
    origin = LatLng(lat=37.5546, lng=126.9706)
    dest = LatLng(lat=37.5759, lng=126.9768)
    
    req = CompareRequest(
        origin=origin,
        destination=dest,
        profile_id=profile.profile_id if profile else "default_profile"
    )
    
    print(f"\nCalling rs.compare_routes for {user_id}...")
    try:
        res = await rs.compare_routes(req, user_id)
        print("SUCCESS! Route found.")
        print(f"Comparison Result: {res.comparison.keys()}")
    except Exception as e:
        print(f"FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    os.environ["GOOGLE_MAPS_API_KEY"] = "AIzaSyAfTKZVCEiQn8ut21lFTS01Uy420QfwqAQ"
    asyncio.run(test_full_route_service())
