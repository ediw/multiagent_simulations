from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List

from models import TimeseriesSnapshot


@dataclass
class MetricsCollector:
    closed_cases: int = 0
    escalated_cases: int = 0
    total_cost: float = 0.0
    total_handoffs: int = 0
    total_reworks: int = 0
    total_subtasks: int = 0
    lead_times: List[float] = field(default_factory=list)
    quality_scores: List[float] = field(default_factory=list)
    routing_counts: Dict[str, int] = field(default_factory=dict)
    agent_busy_time: Dict[str, float] = field(default_factory=dict)
    queue_samples: Dict[str, List[int]] = field(default_factory=dict)
    sla_breaches: int = 0
    false_closures: int = 0
    timeseries: List[TimeseriesSnapshot] = field(default_factory=list)
    effective_temperature_history: List[float] = field(default_factory=list)
    effective_internal_energy_history: List[float] = field(default_factory=list)
    effective_free_energy_history: List[float] = field(default_factory=list)
    effective_entropy_history: List[float] = field(default_factory=list)
    timeout_requeue_count: int = 0

    def record_route(self, src: str, dst: str) -> None:
        key = f"{src}->{dst}"
        self.routing_counts[key] = self.routing_counts.get(key, 0) + 1

    def routing_entropy(self) -> float:
        total = sum(self.routing_counts.values())
        if total == 0:
            return 0.0
        entropy = 0.0
        for count in self.routing_counts.values():
            p = count / total
            entropy -= p * math.log(p + 1e-12)
        return entropy

    def normalized_routing_entropy(self) -> float:
        total = sum(self.routing_counts.values())
        n_routes = len(self.routing_counts)
        if total == 0 or n_routes <= 1:
            return 0.0
        h = self.routing_entropy()
        h_max = math.log(n_routes)
        return h / (h_max + 1e-12)

    def load_entropy(self) -> float:
        avg_loads = []
        for samples in self.queue_samples.values():
            avg_loads.append(statistics.mean(samples) if samples else 0.0)
        total_load = sum(avg_loads)
        if total_load <= 0:
            return 0.0
        entropy = 0.0
        for load in avg_loads:
            if load <= 0:
                continue
            p = load / total_load
            entropy -= p * math.log(p + 1e-12)
        return entropy

    def normalized_load_entropy(self) -> float:
        n_agents = len(self.queue_samples)
        if n_agents <= 1:
            return 0.0
        h = self.load_entropy()
        h_max = math.log(n_agents)
        return h / (h_max + 1e-12)

    def record_effective_thermo_state(
        self,
        effective_temperature: float,
        effective_internal_energy: float,
        effective_entropy: float,
        effective_free_energy: float,
    ) -> None:
        self.effective_temperature_history.append(effective_temperature)
        self.effective_internal_energy_history.append(effective_internal_energy)
        self.effective_entropy_history.append(effective_entropy)
        self.effective_free_energy_history.append(effective_free_energy)

    def queue_imbalance_index(self) -> float:
        sample_means = []
        for samples in self.queue_samples.values():
            if samples:
                sample_means.append(statistics.mean(samples))
        if len(sample_means) < 2:
            return 0.0
        return statistics.pstdev(sample_means)

    def summary(self) -> Dict[str, float]:
        mean_lead = statistics.mean(self.lead_times) if self.lead_times else 0.0
        median_lead = statistics.median(self.lead_times) if self.lead_times else 0.0
        avg_quality = statistics.mean(self.quality_scores) if self.quality_scores else 0.0
        avg_cost_per_case = self.total_cost / self.closed_cases if self.closed_cases else 0.0
        avg_handoffs = self.total_handoffs / self.closed_cases if self.closed_cases else 0.0
        avg_reworks = self.total_reworks / self.closed_cases if self.closed_cases else 0.0
        escalation_rate = self.escalated_cases / self.closed_cases if self.closed_cases else 0.0
        avg_eff_temp = (
            statistics.mean(self.effective_temperature_history)
            if self.effective_temperature_history else 0.0
        )
        avg_eff_u = (
            statistics.mean(self.effective_internal_energy_history)
            if self.effective_internal_energy_history else 0.0
        )
        avg_eff_s = (
            statistics.mean(self.effective_entropy_history)
            if self.effective_entropy_history else 0.0
        )
        avg_eff_f = (
            statistics.mean(self.effective_free_energy_history)
            if self.effective_free_energy_history else 0.0
        )

        return {
            "closed_cases": float(self.closed_cases),
            "mean_lead_time": mean_lead,
            "median_lead_time": median_lead,
            "avg_quality": avg_quality,
            "avg_cost_per_case": avg_cost_per_case,
            "avg_handoffs_per_case": avg_handoffs,
            "avg_reworks_per_case": avg_reworks,
            "escalation_rate": escalation_rate,
            "routing_entropy": self.routing_entropy(),
            "normalized_routing_entropy": self.normalized_routing_entropy(),
            "load_entropy": self.load_entropy(),
            "normalized_load_entropy": self.normalized_load_entropy(),
            "queue_imbalance_index": self.queue_imbalance_index(),
            "avg_effective_temperature": avg_eff_temp,
            "avg_effective_internal_energy": avg_eff_u,
            "avg_effective_entropy": avg_eff_s,
            "avg_effective_free_energy": avg_eff_f,
            "sla_breaches": float(self.sla_breaches),
            "false_closures": float(self.false_closures),
        }
