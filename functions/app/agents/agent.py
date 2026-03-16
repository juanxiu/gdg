import operator
from typing import Annotated, Sequence, TypedDict, Union, Dict, Any, List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from app.config import get_settings
from app.agents.tools import get_candidate_routes, get_environmental_data, get_user_profile, calculate_safety_score
import logging

logger = logging.getLogger("uvicorn")

class AgentState(TypedDict):
    """에이전트 공유 상태"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_id: str
    profile_id: str
    last_observation: Optional[str] # 마지막 도구 실행 결과 요약

class SafePathAgent:
    """SafePath ReAct 에이전트 빌더 및 실행기"""

    def __init__(self):
        settings = get_settings()
        self.tools = [get_candidate_routes, get_environmental_data, get_user_profile, calculate_safety_score]
        self.tool_node = ToolNode(self.tools)
        
        # LLM 설정 및 도구 바인딩
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=settings.google_api_key,
            temperature=0
        ).bind_tools(self.tools)

        # 그래프 정의
        workflow = StateGraph(AgentState)

        # 노드 추가
        workflow.add_node("agent", self._call_model)
        workflow.add_node("action", self.tool_node)

        # 시작점 설정
        workflow.set_entry_point("agent")

        # 조건부 엣지: 도구 호출 여부 판단
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "action",
                "end": END
            }
        )

        # 엣지: 도구 실행 후 다시 에이전트에게 전달
        workflow.add_edge("action", "agent")

        # 컴파일
        self.app = workflow.compile()

    def _should_continue(self, state: AgentState):
        """도구를 더 호출해야 하는지 아니면 답변을 생성할지 결정"""
        messages = state["messages"]
        last_message = messages[-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "continue"
        return "end"

    async def _call_model(self, state: AgentState):
        """LLM 호출 노드"""
        messages = state["messages"]
        
        # 시스템 프롬프트 보강 (상태 기반)
        if len(messages) == 1: # 첫 호출 시
            system_prompt = (
                "당신은 SafePath 서비스의 지능형 에이전트입니다. "
                "사용자의 건강 프로필과 실시간 환경 데이터를 분석하여 가장 안전한 경로를 추천하고 안내해야 합니다.\n"
                "1. 사용자의 프로필(`get_user_profile`)을 먼저 확인하세요.\n"
                "2. 후보 경로(`get_candidate_routes`)를 찾으세요.\n"
                "3. 각 경로의 환경 데이터(`get_environmental_data`)를 수집하고 안전 점수(`calculate_safety_score`)를 계산하세요.\n"
                "4. 모든 정보를 종합하여 사용자에게 친절하게 설명하세요.\n"
                "모든 판단 로직은 제공된 도구를 활용하여 하드코딩 없이 수행하세요."
            )
            # 여기서는 단순히 메시지 리스트에 추가하는 식으로 처리 (간소화)
            # 실제로는 프롬프트 템플릿을 사용하는 것이 좋음
            messages = [HumanMessage(content=system_prompt)] + list(messages)

        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def run(self, user_id: str, profile_id: str, query: str):
        """에이전트 실행 인터페이스"""
        inputs = {
            "messages": [HumanMessage(content=query)],
            "user_id": user_id,
            "profile_id": profile_id
        }
        
        final_state = await self.app.ainvoke(inputs)
        return final_state["messages"][-1].content
