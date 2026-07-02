"""Semantic router sử dụng text-embedding-004.

Sử dụng vector similarity (cosine) với model nhúng để định tuyến chính xác
hơn dựa trên ngữ nghĩa của truy vấn và agent description.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lab_utils.env_setup import load_lab_env


def _cosine(a: list[float], b: list[float]) -> float:
    """Tính khoảng cách Cosine giữa 2 vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(a[i] * b[i] for i in range(len(a)))
    norm_a = math.sqrt(sum(v * v for v in a))
    norm_b = math.sqrt(sum(v * v for v in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class AgentCapability:
    name: str
    description: str
    tags: list[str]


class SemanticRouter:
    """Định tuyến yêu cầu người dùng tới specialist agent phù hợp nhất bằng Embeddings."""

    def __init__(self, agents: list[AgentCapability], threshold: float = 0.5):
        load_lab_env()
        # threshold mặc định cho embedding nên cao hơn (vd: 0.5) vì vector thường có độ tương đồng cao.
        self.agents = agents
        self.threshold = threshold
        
        # Cache embeddings của các agent để không phải gọi API lại mỗi lần route
        from google import genai
        self.client = genai.Client()
        self.agent_embeddings: dict[str, list[float]] = {}
        
        # Pre-compute embeddings cho tất cả agent
        for agent in self.agents:
            corpus = " ".join([agent.description, " ".join(agent.tags)])
            self.agent_embeddings[agent.name] = self._get_embedding(corpus)

    def _get_embedding(self, text: str) -> list[float]:
        """Gọi API Google GenAI lấy embedding."""
        try:
            response = self.client.models.embed_content(
                model='text-embedding-004',
                contents=text,
            )
            return response.embeddings[0].values
        except Exception as e:
            print(f"Lỗi lấy embedding: {e}")
            return []

    def route(self, request: str, top_k: int = 1) -> list[tuple[str, float]]:
        request_vec = self._get_embedding(request)
        if not request_vec:
            return []
            
        scored: list[tuple[str, float]] = []
        for agent in self.agents:
            agent_vec = self.agent_embeddings.get(agent.name, [])
            score = _cosine(request_vec, agent_vec)
            scored.append((agent.name, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def route_with_fallback(
        self,
        request: str,
        fallback: str = "orchestrator",
    ) -> str:
        candidates = self.route(request, top_k=1)
        if not candidates:
            return fallback
        name, score = candidates[0]
        return name if score >= self.threshold else fallback

    def route_with_chain(self, request: str, chain: list[str]) -> str:
        """Thử route chính; nếu điểm < ngưỡng, đi theo chuỗi fallback theo thứ tự.

        Args:
            request: Yêu cầu người dùng.
            chain: Danh sách agent theo thứ tự ưu tiên fallback.
                   Phần tử cuối cùng là fallback cuối cùng (luôn được trả về).

        Returns:
            Tên agent được chọn.
        """
        if not chain:
            return "orchestrator"

        request_vec = self._get_embedding(request)
        if not request_vec:
            return chain[-1]

        # Lấy điểm cho tất cả agent trong chain (trừ fallback cuối)
        candidates_in_chain = [a for a in self.agents if a.name in chain]
        scored: list[tuple[str, float]] = []
        for agent in candidates_in_chain:
            agent_vec = self.agent_embeddings.get(agent.name, [])
            score = _cosine(request_vec, agent_vec)
            scored.append((agent.name, score))

        scored.sort(key=lambda item: item[1], reverse=True)

        # Thử từng ứng viên trong chain theo thứ tự ưu tiên (score cao → thấp)
        for target_name in chain[:-1]:
            for name, score in scored:
                if name == target_name and score >= self.threshold:
                    return name

        # Trả về fallback cuối cùng trong chain
        return chain[-1]
