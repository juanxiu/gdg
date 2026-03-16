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
        
        # 시스템 프롬프트: 페르소나 및 도구 사용 지침 강화
        system_prompt = (
            "당신은 SafePath의 지능형 건강 길잡이입니다. 사용자의 안전과 건강을 최우선으로 합니다.\n\n"
            f"현재 접속 중인 사용자 ID (user_id): `{user_id}`\n\n"
            "### 핵심 지침:\n"
            "1. **정보 수집 (Profiling)**: 사용자의 건강 상태가 파악되지 않았다면, "
            "친절하게 질문하여 정보를 얻으세요. 한 번에 너무 많은 질문을 하지 말고 자연스럽게 대화하세요.\n"
            "2. **프로필 업데이트**: 사용자가 건강 정보를 알려주면 즉시 `update_user_profile`을 호출하세요. "
            f"이때 반드시 위의 `user_id`(`{user_id}`)를 사용하세요.\n"
            "3. **장소 검색**: 사용자가 장소 이름을 말하면 `search_place`로 찾으세요.\n"
            "   - 결과가 단일(`SINGLE_RESULT`)이면 즉시 좌표를 사용하세요.\n"
            "   - 결과가 여러 개(`MULTIPLE_RESULTS`)면 사용자에게 목록을 보여주고 선택을 정중히 요청하세요.\n"
            "   - 사용자가 목록에서 선택하면 선택한 장소의 이름이나 `place_id`를 사용하여 다시 `search_place`를 호출하세요.\n"
            "4. **경로 안내**: 길 안내를 원하면 `get_candidate_routes`와 `calculate_safety_score`를 활용하세요. "
            f"도구 호출 시 `user_id`가 필요하다면 `{user_id}`를 사용하세요.\n"
            "5. **경로 비교**: 경로 비교를 원하면 `compare_routes`를 활용하세요. "
            f"이때도 `user_id`는 `{user_id}`를 사용합니다.\n"
            "6. **언어**: 항상 한국어로 친절하고 전문적으로 답변하세요.\n\n"
            "### 프로필 스키마 (반드시 이 형식으로 update_user_profile 호출):\n"
            "conditions_update의 키와 한국어 매핑:\n"
            "- `respiratory`: 호흡기 질환 (천식, COPD, 비염, 기관지염)\n"
            "- `cardiovascular`: 심혈관 질환 (고혈압, 심장병, 부정맥)\n"
            "- `heatVulnerable`: 온열 질환 취약 (열사병, 더위 취약)\n"
            "- `allergyPollen`: 꽃가루/꽃 알레르기 (화분증, 알레르기 비염)\n\n"
            "각 항목 형식: {\"enabled\": true, \"severity\": \"low\"/\"medium\"/\"high\"}\n"
            "심각도 매핑: 경증/약함 → \"low\", 중등증/보통 → \"medium\", 중증/심함 → \"high\"\n\n"
            "예시) 사용자가 '꽃 알레르기 중증, 비염 경증'이라고 하면:\n"
            "update_user_profile(\n"
            f"  user_id=\"{user_id}\",\n"
            "  conditions_update={\n"
            "    \"allergyPollen\": {\"enabled\": true, \"severity\": \"high\"},\n"
            "    \"respiratory\": {\"enabled\": true, \"severity\": \"low\"}\n"
            "  }\n"
            ")\n\n"
            "### 응답 형식:\n"
            "사용자에게 보여줄 친절한 텍스트 답변을 작성하세요. 장소 목록이 있는 경우 번호를 붙여 깔끔하게 보여주세요."
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
