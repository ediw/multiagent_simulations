from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ============================================================
# ENUMS
# ============================================================


class AgentType(str, Enum):
    INTAKE = "intake"
    CONTEXT = "context"
    EXTRACTION = "extraction"
    VALIDATION = "validation"
    RESOLVER = "resolver"
    HUMAN = "human"
    MEMORY = "memory"


class CaseStatus(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    WAITING = "waiting"
    MERGED = "merged"
    ESCALATED = "escalated"
    CLOSED = "closed"
    FAILED = "failed"


class SubtaskStatus(str, Enum):
    NEW = "new"
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    REWORK = "rework"
    FAILED = "failed"


class EventType(str, Enum):
    CASE_ARRIVAL = "case_arrival"
    AGENT_FINISH = "agent_finish"
    HUMAN_RETURN = "human_return"
    TIMESERIES_SAMPLE = "timeseries_sample"
    SLA_CHECK = "sla_check"
    QUEUE_TIMEOUT_CHECK = "queue_timeout_check"


# ============================================================
# DATA MODEL
# ============================================================


@dataclass
class Subtask:
    subtask_id: str
    parent_case_id: str
    subtask_type: str
    difficulty: float
    required_skill: str
    status: SubtaskStatus = SubtaskStatus.NEW
    assigned_to_agent: Optional[str] = None
    created_by_agent: Optional[str] = None
    confidence: float = 0.0
    quality: float = 0.0
    time_accumulated: float = 0.0
    cost_accumulated: float = 0.0
    partial_result: Dict[str, object] = field(default_factory=dict)
    attempts: int = 0
    enqueue_time: Optional[float] = None


@dataclass
class Case:
    case_id: str
    arrival_time: float
    mail_type: str
    difficulty: float
    priority: int
    attachments_count: int
    attachment_types: List[str]
    uncertainty: float
    deadline: float
    business_process: Optional[str] = None
    intent: Optional[str] = None
    status: CaseStatus = CaseStatus.NEW
    sla_at_risk: bool = False
    handoff_count: int = 0
    rework_count: int = 0
    escalated_to_human: bool = False
    history: List[str] = field(default_factory=list)
    final_quality_score: float = 0.0
    close_time: Optional[float] = None
    total_cost: float = 0.0
    subtasks: Dict[str, Subtask] = field(default_factory=dict)
    merged_result: Dict[str, object] = field(default_factory=dict)


@dataclass
class Agent:
    agent_id: str
    agent_type: AgentType
    skills: Dict[str, float]
    base_accuracy: float
    base_confidence: float
    avg_service_time: float
    queue_capacity: int
    cost_per_action: float
    split_propensity: float
    escalation_threshold: float
    rework_threshold: float
    fatigue_increase: float = 0.02
    fatigue_recovery: float = 0.01
    current_load: float = 0.0
    fatigue_level: float = 0.0
    queue: List[Tuple[str, str]] = field(default_factory=list)  # (case_id, subtask_id)
    busy_until: float = 0.0
    active_item: Optional[Tuple[str, str]] = None
    neighbor_trust_scores: Dict[str, float] = field(default_factory=dict)
    local_success_memory: Dict[str, int] = field(default_factory=dict)
    local_failure_memory: Dict[str, int] = field(default_factory=dict)

    def can_accept(self) -> bool:
        return len(self.queue) < self.queue_capacity

    def utilization(self) -> float:
        return len(self.queue) / max(self.queue_capacity, 1)


@dataclass(order=True)
class Event:
    timestamp: float
    sequence: int
    event_type: EventType = field(compare=False)
    payload: Dict[str, object] = field(compare=False, default_factory=dict)


@dataclass
class TimeseriesSnapshot:
    timestamp: float
    queue_lengths: Dict[str, int]
    queue_lengths_by_type: Dict[str, int]
    fatigue_levels: Dict[str, float]
    cumulative_closed: int
    cumulative_escalated: int
    cumulative_open: int
    trust_scores: Dict[str, float]
    effective_temperature: float = 0.0
    effective_internal_energy: float = 0.0
    effective_entropy: float = 0.0
    effective_free_energy: float = 0.0
    sla_at_risk_count: int = 0
    priority_distribution: Dict[int, int] = field(default_factory=dict)
    cumulative_timeout_requeues: int = 0


@dataclass
class EdgeState:
    base_transfer_cost: float
    latency: float
    historical_success: float = 0.5


@dataclass
class SimulationConfig:
    seed: int = 42
    duration: float = 8 * 60.0
    arrival_rate_per_hour: float = 30.0
    max_rework: int = 2
    split_threshold: float = 1.9
    merge_min_quality: float = 0.72
    human_resolution_time_mean: float = 25.0
    targeted_failure_time: Optional[float] = None
    targeted_failure_agents: List[str] = field(default_factory=list)
    failure_duration: float = 30.0
    burst_start: Optional[float] = None
    burst_end: Optional[float] = None
    burst_multiplier: float = 2.0
    timeseries_sample_interval: float = 2.0
    intra_group_density: float = 0.45
    sla_check_interval: float = 10.0
    sla_risk_threshold_minutes: float = 15.0
    queue_timeout: float = 20.0
    queue_timeout_check_interval: float = 5.0
    trust_reward: float = 0.10
    trust_penalty: float = -0.08
    trust_lambda: float = 0.15
    trust_decay: float = 0.9
    fleet_config: Optional[str] = None
