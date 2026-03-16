from __future__ import annotations

import math

from models import Agent, Case, SimulationConfig, Subtask


class Policies:
    @staticmethod
    def sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def effective_skill(agent: Agent, required_skill: str) -> float:
        return agent.skills.get(required_skill, 0.05)

    @staticmethod
    def effective_confidence(agent: Agent, required_skill: str, difficulty: float, uncertainty: float) -> float:
        skill = Policies.effective_skill(agent, required_skill)
        load_penalty = 0.8 * agent.utilization()
        fatigue_penalty = 0.7 * agent.fatigue_level
        x = 2.0 * skill + 1.0 * agent.base_confidence - 1.1 * difficulty - 0.9 * uncertainty - load_penalty - fatigue_penalty
        return Policies.sigmoid(x)

    @staticmethod
    def effective_quality(agent: Agent, required_skill: str, difficulty: float, uncertainty: float) -> float:
        skill = Policies.effective_skill(agent, required_skill)
        degradation = min(0.85, 0.45 * agent.utilization() + 0.35 * agent.fatigue_level)
        q = agent.base_accuracy * (0.45 + 0.55 * skill) * (1.0 - degradation) * (1.0 - 0.25 * difficulty) * (1.0 - 0.15 * uncertainty)
        return max(0.0, min(1.0, q))

    @staticmethod
    def processing_time(agent: Agent, difficulty: float, attachments_count: int) -> float:
        base = agent.avg_service_time
        return base * (1.0 + 0.55 * difficulty + 0.12 * attachments_count) * (1.0 + 0.5 * agent.utilization() + 0.4 * agent.fatigue_level)

    @staticmethod
    def should_split(case: Case, agent: Agent, config: SimulationConfig) -> bool:
        score = 0.75 * case.difficulty + 0.25 * case.attachments_count + 0.55 * case.uncertainty + 0.3 * agent.split_propensity
        return score > config.split_threshold

    @staticmethod
    def route_score(
        trust: float,
        skill_match: float,
        neighbor_load: float,
        transfer_cost: float,
        historical_success: float,
    ) -> float:
        return 0.24 * trust + 0.26 * skill_match - 0.30 * neighbor_load - 0.13 * transfer_cost + 0.07 * historical_success
        #return 0.32 * trust + 0.28 * skill_match - 0.20 * neighbor_load - 0.10 * transfer_cost + 0.10 * historical_success

    @staticmethod
    def queue_priority(case: Case, subtask: Subtask, now: float, max_rework: int) -> float:
        time_total = case.deadline - case.arrival_time
        time_left = case.deadline - now
        sla_urgency = max(0.0, 1.0 - time_left / max(time_total, 1e-6))
        rework_risk = case.rework_count / max(max_rework + 1, 1)
        return 3.0 * case.priority + 2.0 * sla_urgency + 1.0 * rework_risk

    @staticmethod
    def should_escalate(case: Case, confidence: float, quality: float, agent: Agent, config: SimulationConfig) -> bool:
        threshold = agent.escalation_threshold
        if case.sla_at_risk:
            threshold += 0.10
        return (
            confidence < threshold
            or quality < 0.45
            or case.rework_count > config.max_rework
            or case.uncertainty > 0.88
        )
