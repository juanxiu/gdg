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
        
        if len(messages) == 1:
            system_prompt = (
                "당신은 SafePath의 지능형 건강 길잡이입니다. 사용자의 안전을 최우선으로 합니다.\n"
                "1. 정보를 얻기 위해 도구를 적극적으로 활용하세요.\n"
                "2. 만약 경로 안내에 필요한 사용자의 건강 정보(천식, 알레르기 등)가 부족하다고 판단되면, "
                "추측하지 말고 사용자에게 정중하게 직접 물어보세요.\n"
                "3. 사용자가 정보를 주면 `update_user_profile` 도구를 사용하여 프로필을 최신화하세요.\n"
                "4. 최종 답변은 한국어로 친절하게 제공하세요."
            )
            messages = [HumanMessage(content=system_prompt)] + list(messages)

        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def run(self, user_id: str, profile_id: str, query: str, thread_id: str = "default"):
        """에이전트 실행 (체크포인팅 지원)"""
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id,
            "profile_id": profile_id
        }
        
        # ainvoke를 호출할 때 config(thread_id)를 전달하여 상태 유지
        final_state = await self.app.ainvoke(inputs, config=config)
        return final_state["messages"][-1].content

# 싱글톤 인스턴스 제공 (메모리 세이버 유지를 위함)
_agent_instance = None

def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SafePathAgent()
    return _agent_instance
