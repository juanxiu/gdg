import operator
from typing import Annotated, Sequence, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from app.config import get_settings
from langgraph.checkpoint.memory import MemorySaver
from app.agents.tools import (
    get_candidate_routes, get_environmental_data, 
    get_user_profile, calculate_safety_score, update_user_profile,
    compare_routes, search_place
)
import logging

logger = logging.getLogger("uvicorn")

class AgentState(TypedDict):
    """에이전트 공유 상태"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str

class SafePathAgent:
    """SafePath ReAct 에이전트 빌더 및 실행기 (Phase 2: Conversational)"""

    def __init__(self):
        settings = get_settings()
        self.tools = [
            get_candidate_routes, get_environmental_data, 
            get_user_profile, calculate_safety_score, update_user_profile,
            compare_routes, search_place
        ]
        self.tool_node = ToolNode(self.tools)
        
        # LLM 설정 및 도구 바인딩
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0
        ).bind_tools(self.tools)

        # 체크포인터 (메모리 내 저장, 실제 운영 시 Redis 등 권장)
        self.memory = MemorySaver()

        # 그래프 정의
        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("agent", self._call_model)
        workflow.add_node("action", self.tool_node)

        # 시작점 설정
        workflow.set_entry_point("agent")

        # 조건부 엣지
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "action",
                "end": END
            }
        )

        workflow.add_edge("action", "agent")

        # 컴파일 및 체크포인터 연결
        self.app = workflow.compile(checkpointer=self.memory)

    def _should_continue(self, state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "continue"
        return "end"

    async def _call_model(self, state: AgentState):
        messages = state["messages"]
        user_id = state["user_id"]
        
        # English System Prompt for better reasoning and tool-use precision
        system_prompt = (
            "You are the SafePath Intelligent Health Guide. Your priority is user safety and health during navigation.\n\n"
            f"Current User ID (user_id): `{user_id}`\n\n"
            "### CORE GUIDELINES:\n"
            "1. **Profiling**: If the user's name, age, or health status is unknown (e.g., 'Default User' or age 70), ask politely. Do not overwhelm them with questions. \n"
            "2. **Tool Use**: Use appropriate tools based on user intent. Always use the provided `user_id` for profile and route tools.\n"
            "3. **Language**: Internal reasoning and tool calls are in English, but **YOU MUST RESPOND TO THE USER IN KOREAN** politely and professionally.\n"
            "4. **Data-Driven**: Base your advice on tool outputs. Provide specific details (distance, time, risk) so the frontend can display them.\n"
            "5. **Profile Sync**: When you update health conditions via `update_user_profile`, the system automatically syncs safety weights.\n"
            "6. **Regional Awareness**: In South Korea, walking/bicycle directions are often limited. If a route tool fails or if you are in Korea, **use `TRANSIT` (Public Transport) mode** instead.\n"
            "7. **Streaming Feedback**: You can provide intermediate updates. If a calculation takes time, you can say '안전한 경로를 계산 중입니다. 잠시만 기다려 주세요.' or similar **before** calling the tool.\n\n"
            "### TOOL-SPECIFIC INSTRUCTIONS:\n"
            "- **search_place**: Use this for any location name. \n"
            "- **update_user_profile**: Use this to set `display_name`, `age`, or `conditions_update`.\n"
            "  - Mapping for conditions: `respiratory` (Rhinitis/Asthma), `cardiovascular`, `heatVulnerable`, `allergyPollen`.\n\n"
            "### ONE-SHOT EXAMPLES:\n"
            "User: \"서울역에서 광화문까지 안전한 길 알려줘.\"\n"
            "Thought: I should use TRANSIT mode for Korea. I will give immediate feedback then call tools.\n"
            "Response: \"김연수님, 서울역에서 광화문까지의 경로를 안내해드리겠습니다. 건강 상태를 고려하여 가장 안전한 대중교통 경로를 계산 중이니 잠시만 기다려 주세요.\"\n"
            "Tool Call: compare_routes(user_id=\"...\", origin_lat=..., origin_lng=..., dest_lat=..., dest_lng=..., travel_mode=\"TRANSIT\")\n\n"
            "### FINAL RESPONSE FORMAT:\n"
            "Write a friendly and helpful response in **KOREAN**."
        )

        from langchain_core.messages import SystemMessage
        # 첫 메시지인 경우 시스템 프롬프트 삽입
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=system_prompt)] + list(messages)

        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def run(self, user_id: str, query: str, thread_id: str = "default"):
        """에이전트 실행 (단발성 응답)"""
        async for chunk in self.run_stream(user_id, query, thread_id):
            if chunk["type"] == "final":
                return chunk["content"]
        return "응답을 생성하지 못했습니다."

    async def run_stream(self, user_id: str, query: str, thread_id: str = "default"):
        """에이전트 실시간 스트리밍 실행 (웹소켓용)"""
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id
        }
        
        # astream 활용 (stream_mode="updates")
        last_yielded_content = None
        
        async for event in self.app.astream(inputs, config=config, stream_mode="updates"):
            # event는 노드별 업데이트 내용을 담고 있음
            if "agent" in event:
                message = event["agent"]["messages"][-1]
                content = message.content
                if content and content != last_yielded_content:
                    yield {"type": "partial", "content": content}
                    last_yielded_content = content
        
        # 마지막 상태 확인
        final_state = await self.app.aget_state(config)
        messages = final_state.values.get("messages", [])
        if not messages:
            yield {"type": "final", "content": ""}
            return

        last_message = messages[-1]
        
        # 도구 결과 데이터 추출 (마지막으로 성공한 경로 관련 도구 결과 찾기)
        tool_data = None
        import json
        for msg in reversed(messages):
            if msg.type == "tool":
                try:
                    # 'compare_routes'나 'get_candidate_routes'의 결과인지 확인
                    parsed = json.loads(msg.content)
                    if isinstance(parsed, dict) and ("paths" in parsed or "comparison" in parsed):
                        tool_data = parsed
                        break
                except:
                    continue
        
        # 중복 방지 및 최종 응답 전송
        content = last_message.content if last_message.type == "ai" else ""
        
        if content != last_yielded_content:
            yield {"type": "final", "content": content, "data": tool_data}
        else:
            yield {"type": "final", "content": "", "data": tool_data}

# 싱글톤 인스턴스 제공 (메모리 세이버 유지를 위함)
_agent_instance = None

def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SafePathAgent()
    return _agent_instance
