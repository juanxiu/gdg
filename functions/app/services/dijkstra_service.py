import math
import heapq
from typing import List, Dict, Tuple, Optional
from app.models.common import LatLng
from app.utils.grid import GridManager
from app.services.environment_service import EnvironmentService
from app.services.risk_scorer import RiskScorer

class DijkstraRouter:
    """환경 격자(Grid) 기반의 자체 다익스트라 경로 엔진"""

    def __init__(self, env_service: EnvironmentService, risk_scorer: RiskScorer):
        self.env_service = env_service
        self.risk_scorer = risk_scorer
        self.precision = 0.005 # ~500m

    async def find_path(self, origin: LatLng, destination: LatLng, weights: Dict[str, float]) -> List[LatLng]:
        """좌표간 최적의 격자 경로 탐색"""
        start_node = self._to_node(origin)
        end_node = self._to_node(destination)

        # 우선순위 큐: (total_cost, current_node, path)
        queue = [(0.0, start_node, [start_node])]
        visited = {start_node: 0.0}

        while queue:
            (cost, current, path) = heapq.heappop(queue)

            if current == end_node:
                return [self._node_to_latlng(n) for n in path]

            for neighbor in self._get_neighbors(current):
                # 1. 이동 거리 계산
                dist = self._get_distance(self._node_to_latlng(current), self._node_to_latlng(neighbor))
                
                # 2. 위험도 가중치 계산
                from app.models.route import SegmentEnvironment
                env_dict = await self.env_service.get_for_location(self._node_to_latlng(neighbor))
                env = SegmentEnvironment(**env_dict)
                risk_score = self.risk_scorer.calculate_segment_risk(env, weights)
                
                # 가중치 수식: 거리 * (1 + 위험점수/20) - 위험하면 거리가 6배까지 늘어난 것으로 간주
                # (조정 가능: 위험도가 높을수록 우회하도록 유도)
                penalty = 1.0 + (risk_score / 20.0)
                new_cost = cost + (dist * penalty)

                if neighbor not in visited or new_cost < visited[neighbor]:
                    visited[neighbor] = new_cost
                    # A*를 위한 휴리스틱(직선거리) 추가 가능하나 여기선 순수 다익스트라
                    heapq.heappush(queue, (new_cost, neighbor, path + [neighbor]))
            
            # 무한 루프 방지 (최대 노드 방문 제한)
            if len(visited) > 500:
                break

        return [] # 경로 없음

    def _to_node(self, loc: LatLng) -> Tuple[int, int]:
        return (
            int(round(loc.lat / self.precision)),
            int(round(loc.lng / self.precision))
        )

    def _node_to_latlng(self, node: Tuple[int, int]) -> LatLng:
        return LatLng(
            lat=node[0] * self.precision,
            lng=node[1] * self.precision
        )

    def _get_neighbors(self, node: Tuple[int, int]) -> List[Tuple[int, int]]:
        neighbors = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0: continue
                neighbors.append((node[0] + dx, node[1] + dy))
        return neighbors

    def _get_distance(self, p1: LatLng, p2: LatLng) -> float:
        """두 좌표 간의 직선 거리 (m)"""
        R = 6371000
        phi1, phi2 = math.radians(p1.lat), math.radians(p2.lat)
        dphi = math.radians(p2.lat - p1.lat)
        dlamb = math.radians(p2.lng - p1.lng)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlamb/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))
