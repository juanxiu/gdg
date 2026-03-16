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
    get_user_profile, calculate_safety_score, update_user_profile
)
import logging

logger = logging.getLogger("uvicorn")

class AgentState(TypedDict):
    """에이전트 공유 상태"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    profile_id: str

class SafePathAgent:
    """SafePath ReAct 에이전트 빌더 및 실행기 (Phase 2: Conversational)"""

    def __init__(self):
        settings = get_settings()
        self.tools = [
            get_candidate_routes, get_environmental_data, 
            get_user_profile, calculate_safety_score, update_user_profile
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
        
        # 시스템 프롬프트: 페르소나 및 도구 사용 지침 강화
        system_prompt = (
            "당신은 SafePath의 지능형 건강 길잡이입니다. 사용자의 안전과 건강을 최우선으로 합니다.\n\n"
            "### 핵심 지침:\n"
            "1. **정보 수집 (Profiling)**: 사용자의 건강 상태(호흡기 질환, 알레르기 등)가 파악되지 않았다면, "
            "친절하게 질문하여 정보를 얻으세요. 한 번에 너무 많은 질문을 하지 말고 자연스럽게 대화하세요.\n"
            "2. **도구 활용 (Action)**: 사용자가 정보를 주면 `update_user_profile`을 호출하고, "
            "길 안내를 원하면 `get_candidate_routes`와 `calculate_safety_score` 등을 활용하세요.\n"
            "3. **데이터 기반 답변**: 도구의 결과를 바탕으로 답변하세요. 경로 데이터가 있다면 "
            "프론트엔드가 지도를 그릴 수 있도록 구체적인 정보를 포함해야 합니다.\n"
            "4. **언어**: 항상 한국어로 친절하고 전문적으로 답변하세요.\n\n"
            "### 응답 형식:\n"
            "사용자에게 보여줄 아름다운 텍스트 답변을 작성하세요."
        )

        # 첫 메시지인 경우 시스템 프롬프트 삽입
        if not any(isinstance(m, HumanMessage) and m.content == system_prompt for m in messages):
            # 실제로는 첫 번째 HumanMessage 앞에 위치시키는 것이 좋음
            messages = [HumanMessage(content=system_prompt)] + list(messages)

        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def run(self, user_id: str, profile_id: str, query: str, thread_id: str = "default"):
        """에이전트 실행 (결과물 요약 및 필요시 데이터 포함)"""
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id,
            "profile_id": profile_id
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
