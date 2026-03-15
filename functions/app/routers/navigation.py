from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
import json
import asyncio
import logging
from app.services.route_service import RouteService
from app.models.route import LocationUpdateRequest, LatLng

router = APIRouter(prefix="/api/navigation", tags=["Navigation"])
logger = logging.getLogger("uvicorn")

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, trip_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[trip_id] = websocket

    def disconnect(self, trip_id: str):
        if trip_id in self.active_connections:
            del self.active_connections[trip_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/{trip_id}")
async def navigation_websocket(websocket: WebSocket, trip_id: str):
    await manager.connect(trip_id, websocket)
    service = RouteService()
    
    try:
        while True:
            # 클라이언트로부터 실시간 위치 및 데이터 수신
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 위치 업데이트 처리 (LocationUpdateRequest 형식 가정)
            try:
                if "location" in message:
                    # TODO: 실제 운영 환경에서는 초기 연결 시 토큰 검증을 수행하고 user_id를 고정해야 함
                    user_id = message.get("userId", "anonymous")
                    
                    update_req = LocationUpdateRequest(
                        routeId=trip_id,
                        profileId=message.get("profileId", "default"),
                        location=LatLng(**message["location"])
                    )
                    
                    # 실시간 전방 위험 스캔
                    response = await service.process_location_update(update_req, user_id=user_id)
                    
                    # 결과 즉시 전송
                    await manager.send_personal_message(response.model_dump(), websocket)
                    
                    # 위험 감지 시 자동 재탐색 권장 알림
                    if response.rerouteRecommended:
                        await manager.send_personal_message({
                            "type": "SYSTEM_ALERT",
                            "message": "전방에 위험 구역이 감지되었습니다. 경로 재탐색을 권장합니다.",
                            "severity": "WARNING",
                            "aheadScan": response.aheadScan.model_dump()
                        }, websocket)

            except Exception as e:
                logger.error(f"Error processing navigation data for trip {trip_id}: {e}")
                await manager.send_personal_message({
                    "type": "ERROR", 
                    "message": "데이터 처리 중 오류가 발생했습니다.",
                    "detail": str(e)
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(trip_id)
        logger.info(f"Trip {trip_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        manager.disconnect(trip_id)
