import asyncio
import os
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Mocking the minimal environment for E2E test
GOOGLE_MAPS_API_KEY = "AIzaSyAfTKZVCEiQn8ut21lFTS01Uy420QfwqAQ"
os.environ["GOOGLE_MAPS_API_KEY"] = GOOGLE_MAPS_API_KEY

import sys
sys.path.append(os.path.join(os.getcwd(), 'functions'))

from app.clients.maps_client import MapsClient
from app.models.common import LatLng
from app.models.route import RouteOptions, TravelMode

async def simulate_agent_flow():
    client = MapsClient()
    
    print("--- Step 1: Search for '서울역' ---")
    preds = await client.autocomplete("서울역")
    if not preds:
        print("FAIL: No results for 서울역")
        return
    place_id_origin = preds[0]["place_id"]
    origin_details = await client.get_place_details(place_id_origin)
    origin_lat, origin_lng = origin_details["lat"], origin_details["lng"]
    print(f"Origin: {origin_details['name']} ({origin_lat}, {origin_lng})")

    print("\n--- Step 2: Search for '광화문' ---")
    preds = await client.autocomplete("광화문")
    if not preds:
        print("FAIL: No results for 광화문")
        return
    place_id_dest = preds[0]["place_id"]
    dest_details = await client.get_place_details(place_id_dest)
    dest_lat, dest_lng = dest_details["lat"], dest_details["lng"]
    print(f"Destination: {dest_details['name']} ({dest_lat}, {dest_lng})")

    print("\n--- Step 3: Get Candidate Routes (TRANSIT) ---")
    options = RouteOptions(travelMode=TravelMode.TRANSIT)
    routes = await client.get_candidate_routes(
        LatLng(lat=origin_lat, lng=origin_lng),
        LatLng(lat=dest_lat, lng=dest_lng),
        options
    )
    
    if not routes:
        print("FAIL: No transit routes found between these two points.")
        # Try Directions API v1 directly to see raw output
        import httpx
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode": "transit",
            "key": GOOGLE_MAPS_API_KEY
        }
        async with httpx.AsyncClient() as hclient:
            resp = await hclient.get(url, params=params)
            print(f"Raw Directions API Status: {resp.status_code}")
            print(f"Raw Directions API Body (first 200 chars): {resp.text[:200]}")
    else:
        print(f"SUCCESS: Found {len(routes)} routes.")

if __name__ == "__main__":
    asyncio.run(simulate_agent_flow())
创新
