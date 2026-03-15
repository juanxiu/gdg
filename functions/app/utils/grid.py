import math
from typing import List, Tuple


class GridManager:
    """지역 격자(Grid) 관리 유틸리티 (500m~1km 단위 수집용)"""

    @staticmethod
    def lat_lng_to_grid_id(lat: float, lng: float, precision: float = 0.005) -> str:
        """좌표를 격자 ID로 변환 (0.005 도는 대략 500m)"""
        lat_grid = round(lat / precision) * precision
        lng_grid = round(lng / precision) * precision
        return f"grid_{lat_grid:.4f}_{lng_grid:.4f}"
