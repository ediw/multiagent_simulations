from __future__ import annotations

import heapq
import itertools
import random
import statistics
from typing import Dict, List, Optional, Tuple

from models import (
    Agent,
    AgentType,
    Case,
    CaseStatus,
    Event,
    EventType,
    SimulationConfig,
    Subtask,
    SubtaskStatus,
    TimeseriesSnapshot,
)
from graph import AgentGraph
from metrics import MetricsCollector
from policies import Policies


class MultiAgentMailSimulator:
    def __init__(
        self,
        config: SimulationConfig,
        agents: Dict[str, Agent],
        graph: AgentGraph,
    ) -> None:
        self.config = config
        self.agents = agents
        self.graph = graph
        self.random = random.Random(config.seed)
        self.metrics = MetricsCollector(
            agent_busy_time={a_id: 0.0 for a_id in agents},
            queue_samples={a_id: [] for a_id in agents},
        )
        self._events: List[Event] = []
        self._event_counter = itertools.count()
        self._case_counter = itertools.count(1)
        self._subtask_counter = itertools.count(1)
        self.cases: Dict[str, Case] = {}
        self.unavailable_agents: Dict[str, float] = {}
        self.initial_graph_snapshot: Dict[str, float] = graph.snapshot_trust()

    # -------------------- scheduling --------------------
    def schedule(self, timestamp: float, event_type: EventType, payload: Dict[str, object]) -> None:
        event = Event(timestamp, next(self._event_counter), event_type, payload)
        heapq.heappush(self._events, event)

    def bootstrap(self) -> None:
        t = 0.0
        while t < self.config.duration:
            t += self._sample_interarrival(t)
            if t <= self.config.duration:
                self.schedule(t, EventType.CASE_ARRIVAL, {})
        # Schedule timeseries sampling
        t = self.config.timeseries_sample_interval
        while t <= self.config.duration:
            self.schedule(t, EventType.TIMESERIES_SAMPLE, {})
            t += self.config.timeseries_sample_interval
        # Schedule SLA checks
        t = self.config.sla_check_interval
        while t <= self.config.duration:
            self.schedule(t, EventType.SLA_CHECK, {})
            t += self.config.sla_check_interval
        # Schedule queue timeout checks
        t = self.config.queue_timeout_check_interval
        while t <= self.config.duration:
            self.schedule(t, EventType.QUEUE_TIMEOUT_CHECK, {})
            t += self.config.queue_timeout_check_interval

    def _sample_interarrival(self, now: float) -> float:
        rate_per_min = self.config.arrival_rate_per_hour / 60.0
        if self.config.burst_start is not None and self.config.burst_end is not None:
            if self.config.burst_start <= now <= self.config.burst_end:
                rate_per_min *= self.config.burst_multiplier
        rate_per_min = max(rate_per_min, 1e-6)
        return self.random.expovariate(rate_per_min)

    # -------------------- factories --------------------
    def _new_case(self, timestamp: float) -> Case:
        case_id = f"CASE-{next(self._case_counter):05d}"
        mail_type = self.random.choices(
            population=[
                "simple_mail_no_attachment",
                "mail_with_single_attachment",
                "mail_with_multiple_attachments",
                "ambiguous_mail_with_missing_info",
            ],
            weights=[0.25, 0.35, 0.25, 0.15],
            k=1,
        )[0]

        difficulty_map = {
            "simple_mail_no_attachment": (0.15, 0),
            "mail_with_single_attachment": (0.40, 1),
            "mail_with_multiple_attachments": (0.70, self.random.randint(2, 4)),
            "ambiguous_mail_with_missing_info": (0.85, self.random.randint(0, 2)),
        }
        difficulty, attachments_count = difficulty_map[mail_type]
        attachment_types = []
        for _ in range(attachments_count):
            attachment_types.append(self.random.choice(["pdf", "docx", "xlsx", "image"]))
        uncertainty = min(1.0, max(0.05, difficulty + self.random.uniform(-0.15, 0.15)))
        priority = self.random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15], k=1)[0]
        deadline = timestamp + self.random.uniform(45.0, 240.0)
        return Case(
            case_id=case_id,
            arrival_time=timestamp,
            mail_type=mail_type,
            difficulty=difficulty,
            priority=priority,
            attachments_count=attachments_count,
            attachment_types=attachment_types,
            uncertainty=uncertainty,
            deadline=deadline,
        )

    def _new_subtask(self, case: Case, subtask_type: str, required_skill: str, difficulty: float, created_by_agent: Optional[str]) -> Subtask:
        subtask_id = f"SUB-{next(self._subtask_counter):06d}"
        subtask = Subtask(
            subtask_id=subtask_id,
            parent_case_id=case.case_id,
            subtask_type=subtask_type,
            difficulty=difficulty,
            required_skill=required_skill,
            created_by_agent=created_by_agent,
        )
        case.subtasks[subtask_id] = subtask
        self.metrics.total_subtasks += 1
        return subtask

    # -------------------- run --------------------
    def run(self) -> Dict[str, float]:
        self.bootstrap()
        while self._events:
            event = heapq.heappop(self._events)
            now = event.timestamp
            if now > self.config.duration:
                break
            self._sample_queues()
            self._recover_fatigue()
            self._handle_failures(now)

            if event.event_type == EventType.CASE_ARRIVAL:
                self._on_case_arrival(now)
            elif event.event_type == EventType.AGENT_FINISH:
                self._on_agent_finish(now, event.payload)
            elif event.event_type == EventType.HUMAN_RETURN:
                self._on_human_return(now, event.payload)
            elif event.event_type == EventType.TIMESERIES_SAMPLE:
                self._on_timeseries_sample(now)
            elif event.event_type == EventType.SLA_CHECK:
                self._on_sla_check(now)
            elif event.event_type == EventType.QUEUE_TIMEOUT_CHECK:
                self._on_queue_timeout_check(now)

            self._start_ready_agents(now)

        # Final thermo snapshot
        self._record_thermo_snapshot(self.config.duration)
        return self.metrics.summary()

    # -------------------- timeseries --------------------
    def _on_timeseries_sample(self, now: float) -> None:
        queue_lengths = {a.agent_id: len(a.queue) for a in self.agents.values()}
        by_type: Dict[str, int] = {}
        for a in self.agents.values():
            key = a.agent_type.value
            by_type[key] = by_type.get(key, 0) + len(a.queue)
        fatigue = {a.agent_id: a.fatigue_level for a in self.agents.values()}
        open_count = sum(1 for c in self.cases.values() if c.status in (CaseStatus.ACTIVE, CaseStatus.WAITING))
        trust_scores: Dict[str, float] = {}
        for a in self.agents.values():
            for nb_id, score in a.neighbor_trust_scores.items():
                trust_scores[f"{a.agent_id}->{nb_id}"] = score
        thermo = self._compute_effective_free_energy(now)
        sla_risk_count = sum(
            1 for c in self.cases.values()
            if c.sla_at_risk and c.status in (CaseStatus.ACTIVE, CaseStatus.WAITING)
        )
        priority_dist: Dict[int, int] = {}
        for c in self.cases.values():
            if c.status in (CaseStatus.ACTIVE, CaseStatus.WAITING):
                priority_dist[c.priority] = priority_dist.get(c.priority, 0) + 1
        snapshot = TimeseriesSnapshot(
            timestamp=now,
            queue_lengths=queue_lengths,
            queue_lengths_by_type=by_type,
            fatigue_levels=fatigue,
            cumulative_closed=self.metrics.closed_cases,
            cumulative_escalated=self.metrics.escalated_cases,
            cumulative_open=open_count,
            trust_scores=trust_scores,
            effective_temperature=thermo["effective_temperature"],
            effective_internal_energy=thermo["effective_internal_energy"],
            effective_entropy=thermo["effective_entropy"],
            effective_free_energy=thermo["effective_free_energy"],
            sla_at_risk_count=sla_risk_count,
            priority_distribution=priority_dist,
            cumulative_timeout_requeues=self.metrics.timeout_requeue_count,
        )
        self.metrics.timeseries.append(snapshot)
        self.metrics.record_effective_thermo_state(
            effective_temperature=thermo["effective_temperature"],
            effective_internal_energy=thermo["effective_internal_energy"],
            effective_entropy=thermo["effective_entropy"],
            effective_free_energy=thermo["effective_free_energy"],
        )

    # -------------------- failure / fatigue --------------------
    def _recover_fatigue(self) -> None:
        for agent in self.agents.values():
            if agent.active_item is None:
                recovery = agent.fatigue_recovery * (1.0 - agent.utilization())
                agent.fatigue_level = max(0.0, agent.fatigue_level - recovery)

    def _handle_failures(self, now: float) -> None:
        if self.config.targeted_failure_time is None:
            return
        start = self.config.targeted_failure_time
        end = start + self.config.failure_duration
        for agent_id in self.config.targeted_failure_agents:
            if start <= now <= end:
                if agent_id not in self.unavailable_agents:
                    self._requeue_failed_agent(agent_id, now)
                self.unavailable_agents[agent_id] = end
            else:
                if agent_id in self.unavailable_agents and now > self.unavailable_agents[agent_id]:
                    del self.unavailable_agents[agent_id]

    def _requeue_failed_agent(self, agent_id: str, now: float) -> None:
        agent = self.agents[agent_id]
        orphaned = list(agent.queue)
        agent.queue.clear()
        if agent.active_item is not None:
            orphaned.append(agent.active_item)
            agent.active_item = None

        for case_id, subtask_id in orphaned:
            case = self.cases[case_id]
            if case.status in (CaseStatus.CLOSED, CaseStatus.FAILED, CaseStatus.ESCALATED):
                continue
            subtask = case.subtasks[subtask_id]
            subtask.status = SubtaskStatus.NEW
            subtask.assigned_to_agent = None
            alt = self._find_alternative_agent(agent_id, subtask.required_skill)
            if alt is not None:
                alt.queue.append((case_id, subtask_id))
                subtask.status = SubtaskStatus.QUEUED
                subtask.assigned_to_agent = alt.agent_id
                case.history.append(f"{now:.2f}: requeued {subtask.subtask_type} {agent_id} -> {alt.agent_id}")
            else:
                self._escalate_to_human(case, subtask, now)
                case.history.append(f"{now:.2f}: requeue_failed {subtask.subtask_type}, escalated")

    def _find_alternative_agent(self, failed_agent_id: str, required_skill: str) -> Optional[Agent]:
        failed = self.agents[failed_agent_id]
        candidates = [
            a for a in self.agents.values()
            if a.agent_type == failed.agent_type
            and a.agent_id != failed_agent_id
            and self._is_available(a.agent_id)
            and a.can_accept()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (-a.skills.get(required_skill, 0.0), a.utilization()))
        return candidates[0]

    def _is_available(self, agent_id: str) -> bool:
        return agent_id not in self.unavailable_agents

    # -------------------- event handlers --------------------
    def _on_case_arrival(self, now: float) -> None:
        case = self._new_case(now)
        case.status = CaseStatus.ACTIVE
        case.history.append(f"{now:.2f}: arrived")
        self.cases[case.case_id] = case

        intake_agent = self._pick_best_agent_for_new_case(case)
        if intake_agent is None:
            case.status = CaseStatus.FAILED
            case.history.append(f"{now:.2f}: dropped_no_intake_capacity")
            return

        if Policies.should_split(case, intake_agent, self.config):
            self._create_initial_subtasks(case, intake_agent.agent_id)
            first_subtask_id = list(case.subtasks.keys())[0]
            self._assign_directly(intake_agent, case.case_id, first_subtask_id, now)
            for subtask_id in list(case.subtasks.keys())[1:]:
                self._enqueue_subtask(case.case_id, subtask_id, intake_agent.agent_id, now, is_initial=True)
        else:
            self._new_subtask(case, "mail_understanding", "mail_understanding", case.difficulty, intake_agent.agent_id)
            first_subtask_id = list(case.subtasks.keys())[0]
            self._assign_directly(intake_agent, case.case_id, first_subtask_id, now)

    def _on_agent_finish(self, now: float, payload: Dict[str, object]) -> None:
        agent_id = str(payload["agent_id"])
        case_id = str(payload["case_id"])
        subtask_id = str(payload["subtask_id"])
        agent = self.agents[agent_id]
        case = self.cases[case_id]
        subtask = case.subtasks[subtask_id]

        agent.active_item = None
        quality = Policies.effective_quality(agent, subtask.required_skill, subtask.difficulty, case.uncertainty)
        confidence = Policies.effective_confidence(agent, subtask.required_skill, subtask.difficulty, case.uncertainty)
        subtask.quality = quality
        subtask.confidence = confidence
        subtask.status = SubtaskStatus.DONE
        subtask.attempts += 1
        case.total_cost += agent.cost_per_action
        case.history.append(f"{now:.2f}: {agent_id} finished {subtask.subtask_type} q={quality:.2f} c={confidence:.2f}")

        # MemoryAgent effect: successful lookup reduces case uncertainty
        if subtask.subtask_type == "memory_lookup" and subtask.quality > 0.6:
            case.uncertainty = max(0.05, case.uncertainty - 0.10)
            case.history.append(f"{now:.2f}: memory_lookup reduced uncertainty to {case.uncertainty:.2f}")

        rewarded_value = 1.0 if quality >= 0.7 else 0.0
        lam = self.config.trust_lambda
        if len(case.history) >= 2:
            prev_agent_id = self._extract_previous_agent(case.history[-2])
            if prev_agent_id and prev_agent_id != agent_id and self.graph.has_edge(prev_agent_id, agent_id):
                self.graph.update_success(prev_agent_id, agent_id, rewarded_value, lam)
                src = self.agents[prev_agent_id]
                old_trust = src.neighbor_trust_scores.get(agent_id, 0.5)
                src.neighbor_trust_scores[agent_id] = (1.0 - lam) * old_trust + lam * rewarded_value

        next_action = self._decide_next_action(agent, case, subtask, now)
        if next_action == "close":
            self._close_case(case, now)
        elif next_action == "rework":
            self._send_for_rework(case, subtask, agent, now)
        elif next_action == "escalate":
            self._escalate_to_human(case, subtask, now)
        elif next_action == "merge":
            self._create_merge_subtask(case, agent_id, now)
        else:
            self._route_followup(case, subtask, agent, now)

    def _on_human_return(self, now: float, payload: Dict[str, object]) -> None:
        case_id = str(payload["case_id"])
        case = self.cases[case_id]
        case.escalated_to_human = True
        case.merged_result["human_resolution"] = True
        case.final_quality_score = max(case.final_quality_score, 0.92)
        self._close_case(case, now)

    # -------------------- direct assignment --------------------
    def _assign_directly(self, agent: Agent, case_id: str, subtask_id: str, now: float) -> None:
        case = self.cases[case_id]
        subtask = case.subtasks[subtask_id]
        agent.queue.append((case_id, subtask_id))
        subtask.status = SubtaskStatus.QUEUED
        subtask.assigned_to_agent = agent.agent_id
        subtask.enqueue_time = now
        case.history.append(f"{now:.2f}: assigned {subtask.subtask_type} -> {agent.agent_id} (direct)")

    # -------------------- routing / decisions --------------------
    def _pick_best_agent_for_new_case(self, case: Case) -> Optional[Agent]:
        candidates = [a for a in self.agents.values() if a.agent_type == AgentType.INTAKE and a.can_accept() and self._is_available(a.agent_id)]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (a.utilization(), -a.base_accuracy))
        return candidates[0]

    def _create_initial_subtasks(self, case: Case, creator_agent_id: str) -> None:
        self._new_subtask(case, "mail_understanding", "mail_understanding", min(1.0, case.difficulty * 0.7), creator_agent_id)
        if case.attachments_count > 0:
            self._new_subtask(case, "attachment_extraction", "attachment_extraction", case.difficulty, creator_agent_id)
        self._new_subtask(case, "validation", "validation", min(1.0, case.difficulty * 0.8), creator_agent_id)

    def _enqueue_subtask(self, case_id: str, subtask_id: str, from_agent_id: str, now: float, is_initial: bool = False) -> bool:
        case = self.cases[case_id]
        subtask = case.subtasks[subtask_id]
        target_agent = self._select_target_agent(from_agent_id, subtask.required_skill)
        if target_agent is None:
            gateway = self._pick_human_gateway()
            if gateway is not None:
                self._escalate_to_human(case, subtask, now)
                return True
            return False

        target_agent.queue.append((case_id, subtask_id))
        subtask.status = SubtaskStatus.QUEUED
        subtask.assigned_to_agent = target_agent.agent_id
        subtask.enqueue_time = now
        if not is_initial:
            case.handoff_count += 1
            self.metrics.total_handoffs += 1
            self.metrics.record_route(from_agent_id, target_agent.agent_id)
        case.history.append(f"{now:.2f}: routed {subtask.subtask_type} -> {target_agent.agent_id}")
        return True

    def _select_target_agent(self, from_agent_id: str, required_skill: str) -> Optional[Agent]:
        if from_agent_id not in self.agents:
            return None
        neighbors = self.graph.neighbors(from_agent_id)
        scored: List[Tuple[float, Agent]] = []
        for neighbor_id, edge in neighbors.items():
            if not self._is_available(neighbor_id):
                continue
            agent = self.agents[neighbor_id]
            if not agent.can_accept():
                continue
            trust = self.agents[from_agent_id].neighbor_trust_scores.get(neighbor_id, 0.5)
            skill_match = agent.skills.get(required_skill, 0.05)
            score = Policies.route_score(
                trust=trust,
                skill_match=skill_match,
                neighbor_load=agent.utilization(),
                transfer_cost=edge.base_transfer_cost + edge.latency,
                historical_success=edge.historical_success,
            )
            scored.append((score, agent))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _pick_human_gateway(self) -> Optional[Agent]:
        humans = [a for a in self.agents.values() if a.agent_type == AgentType.HUMAN and self._is_available(a.agent_id)]
        humans = [a for a in humans if a.can_accept()]
        if not humans:
            return None
        humans.sort(key=lambda a: a.utilization())
        return humans[0]

    def _decide_next_action(self, agent: Agent, case: Case, subtask: Subtask, now: float) -> str:
        quality = subtask.quality
        confidence = subtask.confidence

        if Policies.should_escalate(case, confidence, quality, agent, self.config):
            return "escalate"

        if subtask.subtask_type == "validation" and quality < agent.rework_threshold:
            return "rework"

        if self._all_core_subtasks_completed(case):
            if self._merge_quality(case) >= self.config.merge_min_quality:
                return "close"
            return "merge"

        return "route"

    def _all_core_subtasks_completed(self, case: Case) -> bool:
        if not case.subtasks:
            return False
        required_types = {"mail_understanding", "validation"}
        if case.attachments_count > 0:
            required_types.add("attachment_extraction")
        done_types = {s.subtask_type for s in case.subtasks.values() if s.status == SubtaskStatus.DONE}
        return required_types.issubset(done_types)

    def _merge_quality(self, case: Case) -> float:
        completed = [s.quality for s in case.subtasks.values() if s.status == SubtaskStatus.DONE]
        if not completed:
            return 0.0
        return statistics.mean(completed)

    def _send_for_rework(self, case: Case, subtask: Subtask, agent: Agent, now: float) -> None:
        case.rework_count += 1
        self.metrics.total_reworks += 1
        if case.rework_count > self.config.max_rework:
            self._escalate_to_human(case, subtask, now)
            return
        rework_subtask = self._new_subtask(
            case=case,
            subtask_type=subtask.subtask_type,
            required_skill=subtask.required_skill,
            difficulty=min(1.0, subtask.difficulty + 0.05),
            created_by_agent=agent.agent_id,
        )
        self._enqueue_subtask(case.case_id, rework_subtask.subtask_id, agent.agent_id, now)

    def _create_merge_subtask(self, case: Case, from_agent_id: str, now: float) -> None:
        merge_subtask = self._new_subtask(case, "merge_resolution", "merge_resolution", min(1.0, case.difficulty * 0.6), from_agent_id)
        self._enqueue_subtask(case.case_id, merge_subtask.subtask_id, from_agent_id, now)

    def _route_followup(self, case: Case, subtask: Subtask, agent: Agent, now: float) -> None:
        followups = []
        if subtask.subtask_type == "mail_understanding":
            # Optional memory lookup for difficult cases
            if case.difficulty > 0.5 and not self._has_subtask_type(case, "memory_lookup"):
                followups.append(self._new_subtask(
                    case, "memory_lookup", "case_memory",
                    min(1.0, case.difficulty * 0.4), agent.agent_id
                ))
            if case.attachments_count > 0 and not self._has_subtask_type(case, "attachment_extraction"):
                followups.append(self._new_subtask(case, "attachment_extraction", "attachment_extraction", case.difficulty, agent.agent_id))
            if not self._has_subtask_type(case, "validation"):
                followups.append(self._new_subtask(case, "validation", "validation", min(1.0, case.difficulty * 0.8), agent.agent_id))
        elif subtask.subtask_type == "attachment_extraction":
            if not self._has_subtask_type(case, "validation"):
                followups.append(self._new_subtask(case, "validation", "validation", min(1.0, case.difficulty * 0.8), agent.agent_id))
        elif subtask.subtask_type == "merge_resolution":
            if self._merge_quality(case) >= self.config.merge_min_quality:
                self._close_case(case, now)
                return
            else:
                self._escalate_to_human(case, subtask, now)
                return

        for f in followups:
            self._enqueue_subtask(case.case_id, f.subtask_id, agent.agent_id, now)

        if not followups and self._all_core_subtasks_completed(case):
            self._close_case(case, now)

    def _escalate_to_human(self, case: Case, subtask: Subtask, now: float) -> None:
        if case.escalated_to_human:
            return
        gateway = self._pick_human_gateway()
        if gateway is None:
            case.status = CaseStatus.FAILED
            case.history.append(f"{now:.2f}: escalation_failed_no_human_gateway")
            return
        case.status = CaseStatus.ESCALATED
        case.escalated_to_human = True
        self.metrics.escalated_cases += 1
        gateway.queue.append((case.case_id, subtask.subtask_id))
        human_time = self.random.expovariate(1.0 / self.config.human_resolution_time_mean)
        finish_time = now + max(2.0, human_time)
        self.schedule(finish_time, EventType.HUMAN_RETURN, {"case_id": case.case_id, "agent_id": gateway.agent_id})
        case.history.append(f"{now:.2f}: escalated_to_human via {gateway.agent_id}")

    def _close_case(self, case: Case, now: float) -> None:
        case.status = CaseStatus.CLOSED
        case.close_time = now
        case.final_quality_score = max(case.final_quality_score, self._merge_quality(case))
        lead_time = case.close_time - case.arrival_time
        self.metrics.closed_cases += 1
        self.metrics.lead_times.append(lead_time)
        self.metrics.quality_scores.append(case.final_quality_score)
        self.metrics.total_cost += case.total_cost
        if case.close_time > case.deadline:
            self.metrics.sla_breaches += 1
        if case.final_quality_score < 0.50:
            self.metrics.false_closures += 1
        case.history.append(f"{now:.2f}: closed q={case.final_quality_score:.2f}")

    def _has_subtask_type(self, case: Case, subtask_type: str) -> bool:
        return any(s.subtask_type == subtask_type for s in case.subtasks.values())

    def _extract_previous_agent(self, history_line: str) -> Optional[str]:
        for agent_id in self.agents.keys():
            if agent_id in history_line:
                return agent_id
        return None

    # -------------------- SLA / timeout checks --------------------
    def _on_sla_check(self, now: float) -> None:
        for case in self.cases.values():
            if case.status not in (CaseStatus.ACTIVE, CaseStatus.WAITING):
                continue
            if case.sla_at_risk:
                continue
            time_left = case.deadline - now
            if time_left < self.config.sla_risk_threshold_minutes:
                case.sla_at_risk = True
                case.priority = max(case.priority, 3)
                case.history.append(f"{now:.2f}: sla_risk_flagged, priority boosted to {case.priority}")

    def _on_queue_timeout_check(self, now: float) -> None:
        for agent in self.agents.values():
            timed_out: List[Tuple[str, str]] = []
            remaining: List[Tuple[str, str]] = []
            for case_id, subtask_id in agent.queue:
                case = self.cases[case_id]
                subtask = case.subtasks[subtask_id]
                if subtask.enqueue_time is not None and (now - subtask.enqueue_time) > self.config.queue_timeout:
                    timed_out.append((case_id, subtask_id))
                else:
                    remaining.append((case_id, subtask_id))
            agent.queue = remaining

            for case_id, subtask_id in timed_out:
                case = self.cases[case_id]
                if case.status in (CaseStatus.CLOSED, CaseStatus.FAILED, CaseStatus.ESCALATED):
                    continue
                subtask = case.subtasks[subtask_id]
                subtask.status = SubtaskStatus.NEW
                subtask.assigned_to_agent = None
                alt = self._find_alternative_agent(agent.agent_id, subtask.required_skill)
                if alt is not None:
                    alt.queue.append((case_id, subtask_id))
                    subtask.status = SubtaskStatus.QUEUED
                    subtask.assigned_to_agent = alt.agent_id
                    subtask.enqueue_time = now
                    self.metrics.timeout_requeue_count += 1
                    case.history.append(f"{now:.2f}: timeout_requeue {subtask.subtask_type} {agent.agent_id} -> {alt.agent_id}")
                else:
                    self._escalate_to_human(case, subtask, now)

    # -------------------- execution --------------------
    def _start_ready_agents(self, now: float) -> None:
        for agent in self.agents.values():
            if not self._is_available(agent.agent_id):
                continue
            if agent.active_item is not None:
                continue
            if not agent.queue:
                continue
            agent.queue.sort(
                key=lambda item: Policies.queue_priority(
                    self.cases[item[0]], self.cases[item[0]].subtasks[item[1]],
                    now, self.config.max_rework
                ),
                reverse=True,
            )
            case_id, subtask_id = agent.queue.pop(0)
            case = self.cases[case_id]
            subtask = case.subtasks[subtask_id]
            service_time = Policies.processing_time(agent, subtask.difficulty, case.attachments_count)
            finish_time = now + service_time
            agent.active_item = (case_id, subtask_id)
            agent.busy_until = finish_time
            agent.fatigue_level = min(1.0, agent.fatigue_level + agent.fatigue_increase)
            self.metrics.agent_busy_time[agent.agent_id] += service_time
            self.schedule(finish_time, EventType.AGENT_FINISH, {
                "agent_id": agent.agent_id,
                "case_id": case_id,
                "subtask_id": subtask_id,
            })
            case.history.append(f"{now:.2f}: {agent.agent_id} started {subtask.subtask_type}")

    def _sample_queues(self) -> None:
        for agent_id, agent in self.agents.items():
            self.metrics.queue_samples[agent_id].append(len(agent.queue))

    # -------------------- effective thermodynamics --------------------

    def _normalized_open_cases(self) -> float:
        open_cases = sum(
            1 for case in self.cases.values()
            if case.status not in {CaseStatus.CLOSED, CaseStatus.FAILED}
        )
        return min(1.0, open_cases / 50.0)

    def _normalized_rework_pressure(self) -> float:
        open_cases = [
            case for case in self.cases.values()
            if case.status not in {CaseStatus.CLOSED, CaseStatus.FAILED}
        ]
        if not open_cases:
            return 0.0
        avg_rework = statistics.mean(case.rework_count for case in open_cases)
        return min(1.0, avg_rework / max(self.config.max_rework, 1))

    def _normalized_escalation_pressure(self) -> float:
        open_cases = [
            case for case in self.cases.values()
            if case.status not in {CaseStatus.CLOSED, CaseStatus.FAILED}
        ]
        if not open_cases:
            return 0.0
        escalated = sum(1 for case in open_cases if case.escalated_to_human)
        return escalated / len(open_cases)

    def _normalized_sla_risk(self, now: float) -> float:
        open_cases = [
            case for case in self.cases.values()
            if case.status not in {CaseStatus.CLOSED, CaseStatus.FAILED}
        ]
        if not open_cases:
            return 0.0
        risks = []
        for case in open_cases:
            total_window = max(case.deadline - case.arrival_time, 1e-6)
            remaining = case.deadline - now
            risk = 1.0 - max(0.0, remaining) / total_window
            risks.append(max(0.0, min(1.0, risk)))
        return statistics.mean(risks)

    def _mean_uncertainty(self) -> float:
        open_cases = [
            case for case in self.cases.values()
            if case.status not in {CaseStatus.CLOSED, CaseStatus.FAILED}
        ]
        if not open_cases:
            return 0.0
        return statistics.mean(case.uncertainty for case in open_cases)

    def _mean_confidence(self) -> float:
        confidences = []
        for case in self.cases.values():
            if case.status in {CaseStatus.CLOSED, CaseStatus.FAILED}:
                continue
            for subtask in case.subtasks.values():
                if subtask.confidence > 0:
                    confidences.append(subtask.confidence)
        if not confidences:
            return 0.5
        return statistics.mean(confidences)

    def _mean_fatigue(self) -> float:
        if not self.agents:
            return 0.0
        return statistics.mean(agent.fatigue_level for agent in self.agents.values())

    def _mean_queue_length(self) -> float:
        if not self.agents:
            return 0.0
        values = []
        for agent in self.agents.values():
            values.append(len(agent.queue) / max(agent.queue_capacity, 1))
        return statistics.mean(values)

    def _compute_effective_temperature(self) -> float:
        mean_uncertainty = self._mean_uncertainty()
        mean_confidence = self._mean_confidence()
        mean_fatigue = self._mean_fatigue()
        routing_entropy = self.metrics.normalized_routing_entropy()
        t_eff = (
            0.35 * mean_uncertainty
            + 0.25 * (1.0 - mean_confidence)
            + 0.20 * mean_fatigue
            + 0.20 * routing_entropy
        )
        return max(0.0, min(1.0, t_eff))

    def _compute_effective_internal_energy(self, now: float) -> float:
        mean_queue = self._mean_queue_length()
        mean_fatigue = self._mean_fatigue()
        rework_pressure = self._normalized_rework_pressure()
        escalation_pressure = self._normalized_escalation_pressure()
        sla_risk = self._normalized_sla_risk(now)
        open_cases_pressure = self._normalized_open_cases()
        u_eff = (
            0.22 * mean_queue
            + 0.18 * mean_fatigue
            + 0.18 * rework_pressure
            + 0.12 * escalation_pressure
            + 0.15 * sla_risk
            + 0.15 * open_cases_pressure
        )
        return max(0.0, min(1.0, u_eff))

    def _compute_effective_entropy(self) -> float:
        routing_entropy = self.metrics.normalized_routing_entropy()
        load_entropy = self.metrics.normalized_load_entropy()
        s_eff = 0.5 * routing_entropy + 0.5 * load_entropy
        return max(0.0, min(1.0, s_eff))

    def _compute_effective_free_energy(self, now: float) -> Dict[str, float]:
        t_eff = self._compute_effective_temperature()
        u_eff = self._compute_effective_internal_energy(now)
        s_eff = self._compute_effective_entropy()
        f_eff = u_eff - t_eff * s_eff
        return {
            "effective_temperature": t_eff,
            "effective_internal_energy": u_eff,
            "effective_entropy": s_eff,
            "effective_free_energy": f_eff,
        }

    def _record_thermo_snapshot(self, now: float) -> None:
        thermo = self._compute_effective_free_energy(now)
        self.metrics.record_effective_thermo_state(
            effective_temperature=thermo["effective_temperature"],
            effective_internal_energy=thermo["effective_internal_energy"],
            effective_entropy=thermo["effective_entropy"],
            effective_free_energy=thermo["effective_free_energy"],
        )
