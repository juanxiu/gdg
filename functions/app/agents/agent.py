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
            "1. **Profiling**: If the user's health status is unknown, ask politely. Do not overwhelm them with questions.\n"
            "2. **Tool Use**: Use appropriate tools based on user intent. Always use the provided `user_id` for profile and route tools.\n"
            "3. **Language**: Internal reasoning and tool calls are in English, but **YOU MUST RESPOND TO THE USER IN KOREAN** politely and professionally.\n"
            "4. **Data-Driven**: Base your advice on tool outputs. Provide specific details (distance, time, risk) so the frontend can display them.\n\n"
            "### TOOL-SPECIFIC INSTRUCTIONS:\n"
            "- **search_place**: Use this for any location name. \n"
            "  - If `SINGLE_RESULT`, proceed with coordinates.\n"
            "  - If `MULTIPLE_RESULTS`, list options and ask the user to choose.\n"
            "- **update_user_profile**: Map Korean symptoms to these keys:\n"
            "  - `respiratory`: Rhinitis(비염), Asthma(천식), COPD, Bronchitis.\n"
            "  - `cardiovascular`: Hypertension(고혈압), Heart disease, Arrhythmia.\n"
            "  - `heatVulnerable`: Heatstroke(열사병), vulnerable to heat.\n"
            "  - `allergyPollen`: Pollen allergy(꽃가루 알레르기/화분증).\n"
            "- **compare_routes**: Use this when the user wants to see the difference between safest and fastest paths.\n\n"
            "### ONE-SHOT EXAMPLES:\n"
            "Example 1: Update Profile\n"
            "User: \"꽃 알레르기가 심하고 비염이 약간 있어.\"\n"
            f"Tool Call: update_user_profile(user_id=\"{user_id}\", conditions_update={{\"allergyPollen\": {{\"enabled\": true, \"severity\": \"high\"}}, \"respiratory\": {{\"enabled\": true, \"severity\": \"low\"}}}})\n\n"
            "Example 2: Search Place (Ambiguous)\n"
            "User: \"샌프란시스코로 가고 싶어.\"\n"
            "Tool Call: search_place(query=\"San Francisco\")\n"
            "Response (if multiple): \"샌프란시스코와 관련된 장소를 여러 개 찾았습니다. 어디를 말씀하시는 건가요? 1. 샌프란시스코(CA) 2. 샌프란시스코 국제공항...\"\n\n"
            "Example 3: Search Place (Direct Choice)\n"
            "User: \"1번으로 해줘.\"\n"
            "Tool Call: search_place(query=\"San Francisco\", place_id=\"ChIJIQBpAG2ahYAR_6128GcTUEo\")\n\n"
            "Example 4: Route Search\n"
            "User: \"강남역에서 서초역까지 가는 길 알려줘.\"\n"
            "Step 1: search_place(query=\"강남역\") -> {lat: 37.497, lng: 127.027}\n"
            "Step 2: search_place(query=\"서초역\") -> {lat: 37.491, lng: 127.007}\n"
            "Step 3: get_candidate_routes(origin_lat=37.497, origin_lng=127.027, dest_lat=37.491, dest_lng=127.007)\n\n"
            "Example 5: Environmental Check & Score\n"
            "User: \"여기 미세먼지 어때?\"\n"
            "Step 1: get_environmental_data(locations=[{\"lat\": ..., \"lng\": ...}])\n"
            "Step 2: get_user_profile(user_id=\"...\")\n"
            "Step 3: calculate_safety_score(environment_data=..., profile_conditions=[\"allergyPollen\"])\n\n"
            "Example 6: Compare Routes\n"
            "User: \"가장 안전한 길이랑 빠른 길 비교해줘.\"\n"
            "Tool Call: compare_routes(user_id=\"...\", origin_lat=..., origin_lng=..., dest_lat=..., dest_lng=...)\n\n"
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
        """에이전트 실행 (결과물 요약 및 필요시 데이터 포함)"""
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id
        }
        
        final_state = await self.app.ainvoke(inputs, config=config)
        last_message = final_state["messages"][-1]
        
        # 도구 호출 결과 등이 포함되었는지 확인 (현재는 텍스트만 리턴하지만 확장 가능)
        # 만약 도구 결과물 자체를 프론트에 넘겨야 한다면 여기서 state를 분석하여 구조화할 수 있음
        return last_message.content

# 싱글톤 인스턴스 제공 (메모리 세이버 유지를 위함)
_agent_instance = None

def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SafePathAgent()
    return _agent_instance
