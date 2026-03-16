import logging
from typing import Optional, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from app.config import get_settings
from app.models.common import RiskLevel, HazardType
from app.models.route import LocationUpdateResponse, AheadScan, AheadHazard

logger = logging.getLogger("uvicorn")

class LLMRecommendation(BaseModel):
    """LLM이 생성한 안내 문구 구조"""
    recommendation: str = Field(..., description="사용자 맞춤형 추천 문구 (자연어)")
    reason: str = Field(..., description="추천의 논리적 근거 (데이터 기반)")

class LLMNavigationAlert(BaseModel):
    """LLM이 생성한 실시간 내비게이션 알림 구조"""
    message: str = Field(..., description="위험 상황에 대한 자연어 설명 및 대처 요령")
    severity: RiskLevel = Field(..., description="위험도 등급")

class LLMService:
    """LLM (Gemini) 기반 지능형 가이드 서비스"""

    def __init__(self):
        settings = get_settings()
        if not settings.google_api_key:
            logger.warning("GOOGLE_API_KEY is not set. LLM features may fallback to static templates.")
            self.llm = None
        else:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=settings.google_api_key,
                temperature=0.7
            )

    async def generate_route_recommendation(
        self, 
        safe_path_data: Dict[str, Any], 
        fastest_path_data: Dict[str, Any], 
        profile_data: Dict[str, Any]
    ) -> LLMRecommendation:
        """안전 경로와 최단 경로를 비교하여 맞춤형 추천 사유 생성"""
        if not self.llm:
            return LLMRecommendation(
                recommendation="안전 경로를 권장합니다.",
                reason="최단 경로 대비 위험도가 낮습니다."
            )

        parser = PydanticOutputParser(pydantic_object=LLMRecommendation)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "당신은 안전한 보행을 돕는 'SafePath' 서비스의 지능형 비서입니다.\n"
                "사용자의 건강 프로필과 두 가지 경로 데이터를 분석하여, 어떤 경로가 왜 더 적합한지 설명하세요.\n"
                "반드시 제시된 형식(JSON)으로 응답하세요.\n\n"
                "{format_instructions}"
            )),
            ("human", (
                "1. 사용자 프로필: {profile}\n"
                "2. 안전 최우선 경로: {safe_path}\n"
                "3. 최단 시간 경로: {fastest_path}\n\n"
                "두 경로를 비교하고, 사용자의 건강 상태를 고려한 설득력 있는 추천 사유를 생성해줘."
            ))
        ])

        chain = prompt | self.llm | parser

        try:
            result = await chain.ainvoke({
                "profile": profile_data,
                "safe_path": safe_path_data,
                "fastest_path": fastest_path_data,
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"LLM route recommendation failed: {e}")
            return LLMRecommendation(
                recommendation="안전 경로를 권장합니다.",
                reason="추천 사유 생성 중 오류가 발생했으나, 데이터 분석 결과 이 경로가 더 안전합니다."
            )

    async def generate_navigation_alert(
        self,
        hazard_data: Dict[str, Any],
        profile_data: Dict[str, Any]
    ) -> LLMNavigationAlert:
        """실시간 위험 상황에 대한 자연어 알림 및 대처 요령 생성"""
        if not self.llm:
            return LLMNavigationAlert(
                message="전방에 위험 구역이 감지되었습니다. 경로 재탐색을 권장합니다.",
                severity=RiskLevel.WARNING
            )

        parser = PydanticOutputParser(pydantic_object=LLMNavigationAlert)

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "당신은 내비게이션 안내 전문가입니다. 사용자의 전방에 탐지된 위험 요소를 분석하여 자연스러운 경고 문구와 대처 요령을 생성하세요.\n"
                "사용자의 건강 프로필을 고려하여 더욱 구체적으로 안내하세요.\n"
                "반드시 제시된 형식(JSON)으로 응답하세요.\n\n"
                "{format_instructions}"
            )),
            ("human", (
                "1. 탐지된 위험 정보: {hazard}\n"
                "2. 사용자 프로필: {profile}\n\n"
                "위험을 알리고 사용자가 어떻게 행동해야 할지 짧고 명확하게 알려줘."
            ))
        ])

        chain = prompt | self.llm | parser

        try:
            result = await chain.ainvoke({
                "hazard": hazard_data,
                "profile": profile_data,
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"LLM navigation alert failed: {e}")
            return LLMNavigationAlert(
                message="전방에 환경 위험이 감지되었습니다. 건강을 위해 우회하거나 마스크 착용을 권장합니다.",
                severity=RiskLevel.WARNING
            )
