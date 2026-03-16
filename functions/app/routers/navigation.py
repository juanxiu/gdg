from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
import json
import logging
from app.services.route_service import RouteService
from app.models.route import LocationUpdateRequest, LatLng
from app.config import get_settings

router = APIRouter(prefix="/api/navigation", tags=["Navigation"])
logger = logging.getLogger("uvicorn")

async def authenticate_websocket(websocket: WebSocket, token: str) -> dict:
    """웹소켓 연결 시 Firebase 토큰 검증"""
    settings = get_settings()
    
    # 로컬 환경 테스트용
    if settings.environment == "local":
        return {"uid": "1", "email": "test@safepath.dev"}
        
    if not token:
        logger.warning("WebSocket connection attempt missing token query parameter")
        return None

    try:
        import firebase_admin
        from firebase_admin import auth
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
            
        decoded_token = auth.verify_id_token(token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email"),
        }
    except Exception as e:
        logger.error(f"WebSocket auth failed for token {token[:10]}...: {e}")
        return None

class ConnectionManager:
    def __init__(self):
        # routeId -> WebSocket 매핑
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, routeId: str, websocket: WebSocket):
        await websocket.accept()
        # 기존 연결이 있다면 정리 (중복 연결 방지)
        if routeId in self.active_connections:
            try:
                await self.active_connections[routeId].close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
        self.active_connections[routeId] = websocket

    def disconnect(self, routeId: str):
        if routeId in self.active_connections:
            del self.active_connections[routeId]
            logger.info(f"Connection for route {routeId} removed from manager")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

manager = ConnectionManager()

@router.get("/ws/{routeId}", summary="[WebSocket] 실시간 내비게이션 연결", description="**이 엔드포인트는 WebSocket 프로토콜(wss://) 전용입니다.**\n\n- **연결 방법**: `wss://{domain}/api/navigation/ws/{routeId}?token={Firebase_ID_Token}`\n- **테스트 방법**: Postman의 WebSocket 또는 `wscat` 등을 이용하세요.")
async def websocket_documentation(routeId: str, token: str = Query(..., description="Firebase ID Token")):
    return {"message": "WebSocket 전용 엔드포인트입니다. wss:// 프로토콜로 연결하세요."}

@router.websocket("/ws/{routeId}")
async def navigation_websocket(
    websocket: WebSocket, 
    routeId: str,
    token: str = Query(None)
):
    # 1. 인증 확인
    user_info = await authenticate_websocket(websocket, token)
    if not user_info:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(routeId, websocket)
    service = RouteService()
    user_id = user_info["uid"]
    
    try:
        while True:
            try:
                # 클라이언트로부터 실시간 위치 및 데이터 수신
                data = await websocket.receive_text()
                message = json.loads(data)
                
                if "location" in message:
                    update_req = LocationUpdateRequest(
                        routeId=routeId,
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
                            "message": response.message or "전방에 위험 구역이 감지되었습니다. 경로 재탐색을 권장합니다.",
                            "severity": "WARNING",
                            "aheadScan": response.aheadScan.model_dump()
                        }, websocket)
                else:
                    await manager.send_personal_message({
                        "type": "ERROR",
                        "message": "잘못된 데이터 형식입니다. 'location' 필드가 필요합니다."
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "ERROR",
                    "message": "유효하지 않은 JSON 형식입니다."
                }, websocket)
            except Exception as e:
                logger.error(f"Error processing navigation data for route {routeId}: {e}")
                await manager.send_personal_message({
                    "type": "ERROR", 
                    "message": "데이터 처리 중 오류가 발생했습니다.",
                    "detail": str(e)
                }, websocket)

    except WebSocketDisconnect:
        logger.info(f"Route {routeId} disconnected by client")
    except Exception as e:
        logger.error(f"WebSocket Error for route {routeId}: {e}")
    finally:
        manager.disconnect(routeId)
        try:
            await websocket.close()
        except Exception:
            pass
