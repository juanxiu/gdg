from typing import Dict, List
from app.models.profile import HealthConditions, CustomWeights
from app.models.route import SegmentEnvironment, RiskLevel


class RiskScorer:
    """Health Risk Score 규칙 기반 엔진 (Phase 1)"""

    # 질환별 가중치 프리셋 (심각도 Medium 기준)
    # 가중치 합이 10이 되도록 정규화하여 사용하거나, 가중평균 방식으로 계산
    WEIGHT_PRESETS = {
        "respiratory": {
            "pm25": 4.0, "pm10": 2.5, "no2": 2.0, "o3": 1.0,
            "pollen": 0.5, "temperature": 0.0, "shade": 0.0, "slope": 0.0
        },
        "cardiovascular": {
            "pm25": 2.5, "pm10": 1.5, "no2": 1.5, "o3": 0.5,
            "pollen": 0.0, "temperature": 2.5, "shade": 1.0, "slope": 0.5
        },
        "heatVulnerable": {
            "pm25": 0.5, "pm10": 0.5, "no2": 0.0, "o3": 0.0,
            "pollen": 0.0, "temperature": 5.0, "shade": 3.0, "slope": 1.0
        },
        "allergyPollen": {
            "pm25": 1.0, "pm10": 1.0, "no2": 0.0, "o3": 0.0,
            "pollen": 7.0, "temperature": 0.0, "shade": 1.0, "slope": 0.0
        },
    }

    @staticmethod
    def resolve_weights(conditions: HealthConditions, custom: CustomWeights = None) -> Dict[str, float]:
        """사용자 프로필 기반 최종 가중치 산정"""
        if custom:
            return custom.model_dump()

        # 여러 질환이 있을 경우 가중치 합산 후 정규화
        combined_weights = {
            "pm25": 0.0, "pm10": 0.0, "no2": 0.0, "o3": 0.0,
            "pollen": 0.0, "temperature": 0.0, "shade": 0.0, "slope": 0.0
        }

        active_count = 0
        for cond_name, detail in conditions.model_dump().items():
            if detail["enabled"] and cond_name in RiskScorer.WEIGHT_PRESETS:
                active_count += 1
                preset = RiskScorer.WEIGHT_PRESETS[cond_name]
                
                # 심각도에 따른 배수 (low: 0.7, medium: 1.0, high: 1.5)
                multiplier = 1.0
                if detail["severity"] == "low": multiplier = 0.7
                elif detail["severity"] == "high": multiplier = 1.5

                for key in combined_weights:
                    combined_weights[key] += preset.get(key, 0.0) * multiplier

        if active_count == 0:
            # 기본값 (일반인)
            return {"pm25": 1.0, "pm10": 1.0, "no2": 1.0, "o3": 1.0, "pollen": 1.0, "temperature": 1.0, "shade": 1.0, "slope": 1.0}

        return combined_weights

    @staticmethod
    def normalize_aqi(aqi: int) -> float:
        """AQI(0~500+)를 0~1 범위로 정규화"""
        return min(aqi / 200.0, 1.0)  # 200 이상이면 매우 나쁨(1.0)

    @staticmethod
    def normalize_pollen(level: int) -> float:
        """꽃가루 레벨(0~5)을 0~1 범위로 정규화"""
        return level / 5.0

    @staticmethod
    def normalize_temp(feels_like: float) -> float:
        """체감온도를 0~1 범위로 정규화 (30도 기준)"""
        if feels_like < 25: return 0.0
        return min((feels_like - 25) / 10.0, 1.0)  # 35도 이상이면 최고 위험

    @staticmethod
    def calculate_segment_risk(env: SegmentEnvironment, weights: Dict[str, float]) -> int:
        """단일 세그먼트의 Risk Score (0~100) 계산"""
        
        # 1. 요소별 정규화 점수 (0~1)
        scores = {
            "pm25": RiskScorer.normalize_aqi(int(env.pm25)), # 실제론 농도지만 AQI 수식과 유사하게 취급
            "pm10": RiskScorer.normalize_aqi(int(env.pm10)),
            "no2": RiskScorer.normalize_aqi(int(env.no2)),
            "o3": RiskScorer.normalize_aqi(int(env.o3)),
            "temperature": RiskScorer.normalize_temp(env.feelsLike),
            "pollen": RiskScorer.normalize_pollen(env.pollenLevel),
            "shade": 1.0 - env.shadeRatio, # 그늘이 많을수록(1.0) 위험도 낮음(0.0)
            "slope": min(env.slope / 15.0, 1.0) # 15% 경사면 최고 위험
        }

        # 2. 가중합 계산
        weighted_sum = 0.0
        total_weight = 0.0
        for key, weight in weights.items():
            weighted_sum += scores.get(key, 0.0) * weight
            total_weight += weight

        if total_weight == 0: return 0
        
        # 3. 0~100 스케일링
        final_score = (weighted_sum / total_weight) * 100
        return int(min(max(final_score, 0), 100))

    @staticmethod
    def classify_risk(score: int) -> RiskLevel:
        """점수에 따른 등급 분류"""
        if score < 20: return RiskLevel.SAFE
        if score < 50: return RiskLevel.CAUTION
        if score < 80: return RiskLevel.WARNING
        return RiskLevel.DANGER
