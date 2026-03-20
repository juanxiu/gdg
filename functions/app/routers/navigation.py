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
        # user_id -> WebSocket 매핑
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        # 기존 연결이 있다면 정리 (중복 연결 방지)
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"Connection for user {user_id} removed from manager")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

manager = ConnectionManager()

@router.get("/ws", summary="[WebSocket] 실시간 내비게이션 및 채팅 연결 가이드", description=(
    "**이 엔드포인트는 WebSocket 프로토콜(wss://) 전용 가이드입니다.**\n\n"
    "### 1. 연결 방법\n"
    "`wss://{domain}/api/navigation/ws?token={Firebase_ID_Token}`\n\n"
    "### 2. 메시지 규격 (Client -> Server)\n"
    "- **채팅/질문**: `{\"chat\": \"강남역 가는 길 알려줘\"}` 또는 일반 텍스트\n"
    "- **위치 업데이트**: `{\"location\": {\"lat\": 37.5, \"lng\": 127.0}, \"routeId\": \"route_abc123\"}`\n\n"
    "### 3. 메시지 규격 (Server -> Client)\n"
    "- **에이전트 답변**: `{\"type\": \"CHAT_RESPONSE\", \"message\": \"...\", \"data\": { ... }}`\n"
    "- **위험 알림**: `{\"type\": \"SYSTEM_ALERT\", \"severity\": \"WARNING\", ...}`"
))
async def websocket_documentation(token: str = Query(..., description="Firebase ID Token")):
    return {"message": "WebSocket 전용 엔드포인트입니다. 안내된 wss:// 프로토콜로 연결하세요."}

@router.websocket("/ws")
async def navigation_websocket(
    websocket: WebSocket, 
    token: str = Query(None)
):
    # 1. 인증 확인
    user_info = await authenticate_websocket(websocket, token)
    if not user_info:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = user_info["uid"]
    await manager.connect(user_id, websocket)
    service = RouteService()
    
    try:
        while True:
            try:
                # 클라이언트로부터 실시간 위치 및 데이터 수신
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    message = data # JSON이 아니면 일반 문자열로 처리

                if isinstance(message, dict) and "location" in message:
                    # 위치 업데이트 시 routeId는 메시지 본문에서 가져옴
                    route_id = message.get("routeId")
                    if not route_id:
                        await manager.send_personal_message({
                            "type": "ERROR",
                            "message": "위치 업데이트에는 'routeId' 필드가 필요합니다."
                        }, websocket)
                        continue

                    update_req = LocationUpdateRequest(
                        routeId=route_id,
                        profile_id="default",
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
                elif isinstance(message, str) or (isinstance(message, dict) and "chat" in message):
                    # 사용자의 직접적인 채팅 메시지 처리 (프로필 답변, 질문 등)
                    chat_query = message if isinstance(message, str) else message["chat"]
                    
                    from app.agents.agent import get_agent
                    agent = get_agent()
                    
                    # thread_id를 user_id로 고정하여 대화 문맥 유지
                    async for chunk in agent.run_stream(
                        user_id=user_id, 
                        query=chat_query, 
                        thread_id=user_id
                    ):
                        if chunk["content"]:
                            # 결과 전송
                            await manager.send_personal_message({
                                "type": "CHAT_RESPONSE",
                                "subtype": chunk["type"], # partial or final
                                "message": chunk["content"],
                                "data": chunk.get("data"), # 구조화된 데이터 추가
                                "timestamp": message.get("timestamp") if isinstance(message, dict) else None
                            }, websocket)
                else:
                    await manager.send_personal_message({
                        "type": "ERROR",
                        "message": "잘못된 데이터 형식입니다. 'location' 또는 'chat' 필드가 필요합니다."
                    }, websocket)

            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "ERROR",
                    "message": "유효하지 않은 JSON 형식입니다."
                }, websocket)
            except Exception as e:
                import traceback
                logger.error(f"Error processing data for user {user_id}: {e}\n{traceback.format_exc()}")
                await manager.send_personal_message({
                    "type": "ERROR", 
                    "message": "요청 처리 중 오류가 발생했습니다.",
                    "detail": str(e),
                    "hint": "네트워크 상태를 확인하거나 잠시 후 다시 시도해주세요."
                }, websocket)

    except WebSocketDisconnect:
        logger.info(f"User {user_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error for user {user_id}: {e}")
    finally:
        manager.disconnect(user_id)
        try:
            await websocket.close()
        except Exception:
            pass
