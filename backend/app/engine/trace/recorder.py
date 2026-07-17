"""OS2 provenance recorder and queryable trace graph."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


class TraceNode(BaseModel):
    node_id: str
    node_type: str
    tick: int
    agent_id: Optional[str] = None
    payload_ref: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class TraceEdge(BaseModel):
    from_id: str
    to_id: str
    edge_type: str


class TraceGraph:
    def __init__(self, tick: int):
        self.tick = tick
        self.nodes: List[TraceNode] = []
        self.edges: List[TraceEdge] = []
        self._node_index: Dict[str, TraceNode] = {}

    def add_node(self, node: TraceNode) -> None:
        self.nodes.append(node)
        self._node_index[node.node_id] = node

    def add_edge(self, edge: TraceEdge) -> None:
        self.edges.append(edge)

    def get_node(self, node_id: str) -> Optional[TraceNode]:
        return self._node_index.get(node_id)

    def get_ancestors(self, node_id: str) -> List[TraceNode]:
        reverse: Dict[str, List[str]] = {}
        for edge in self.edges:
            reverse.setdefault(edge.to_id, []).append(edge.from_id)
        visited: Set[str] = set()
        queue = [node_id]
        output: List[TraceNode] = []
        while queue:
            current = queue.pop(0)
            for parent_id in reverse.get(current, []):
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                parent = self.get_node(parent_id)
                if parent:
                    output.append(parent)
                queue.append(parent_id)
        return output


class TraceRecorder:
    def __init__(self, scenario_name: str):
        self._scenario_name = scenario_name
        self._recorder: Any = None
        self._tick_records: List[Dict[str, Any]] = []
        self._tick_graphs: List[TraceGraph] = []
        self._global_node_index: Dict[str, TraceNode] = {}
        self._export_base_dir: Optional[str] = None
        self._exported_run_dir: Optional[str] = None

    def initialize(self) -> None:
        from app.framework.recording.recorder import RunRecorder
        self._recorder = RunRecorder(scenario_name=self._scenario_name)

    def set_agents(self, agent_ids: List[str]) -> None:
        if self._recorder:
            self._recorder.set_agents(agent_ids)

    def configure_run(
        self,
        *,
        export_base_dir: str,
        scenario_version: str,
        random_seed: int,
        scenario_config: Dict[str, Any],
        agent_models: Dict[str, Dict[str, Any]],
    ) -> None:
        self._export_base_dir = export_base_dir
        if not self._recorder:
            return
        self._recorder._scenario_version = scenario_version
        self._recorder._random_seed = random_seed
        self._recorder.set_scenario_config(scenario_config)
        for agent_id, model_info in agent_models.items():
            self._recorder.set_agent_model(agent_id, model_info)

    def record_tick(
        self,
        *,
        tick: int,
        state: Any = None,
        agent_logs: Optional[List[Any]] = None,
        assessment_cases: Optional[List[Any]] = None,
        tool_runs: Optional[List[Any]] = None,
        world_snapshot: Optional[Dict[str, Any]] = None,
        os2_world_actions: Optional[List[Any]] = None,
        os2_external_observations: Optional[List[Any]] = None,
        os2_world_events: Optional[List[Any]] = None,
        os2_settlements: Optional[List[Any]] = None,
        os2_director_plan: Any = None,
        director_harness_trace: Any = None,
        **_ignored: Any,
    ) -> None:
        actions = list(os2_world_actions or [])
        observations = list(os2_external_observations or [])
        events = list(os2_world_events or [])
        settlements = list(os2_settlements or [])
        payload = {
            "tick": tick,
            "os2_world_actions": [_dump(item) for item in actions],
            "os2_external_observations": [_dump(item) for item in observations],
            "os2_world_events": [_dump(item) for item in events],
            "os2_settlements": [_dump(item) for item in settlements],
            "os2_director_plan": _dump(os2_director_plan) if os2_director_plan else None,
            "director_harness_trace": (
                _dump(director_harness_trace) if director_harness_trace else None
            ),
            "world_snapshot": dict(world_snapshot or {}),
        }
        self._tick_records.append(payload)
        if self._recorder:
            self._recorder.record_tick(
                tick=tick,
                state=state,
                agent_logs=agent_logs,
                assessment_cases=assessment_cases,
                tool_runs=tool_runs,
                world_snapshot=world_snapshot,
                world_actions=actions,
                external_observations=observations,
                world_events=events,
                settlements=settlements,
                director_plan=os2_director_plan,
                director_harness_trace=director_harness_trace,
            )
        graph = self._build_tick_graph(
            tick, actions, observations, events, settlements,
            os2_director_plan, director_harness_trace,
        )
        self._tick_graphs.append(graph)
        self._global_node_index.update({node.node_id: node for node in graph.nodes})

    def finalize(self, state: Any) -> Optional[str]:
        if not self._recorder:
            return None
        self._recorder.finalize(state)
        if self._export_base_dir:
            self._exported_run_dir = self._recorder.export_directory(
                self._export_base_dir
            )
        return self._exported_run_dir

    def flush_partial(self) -> Optional[str]:
        """把已录制的 ticks/ledgers 增量落盘（不做终局 finalize）。

        实时局一跑一小时，此前只有终局才导出结构化账本——中途暂停或
        崩溃会丢掉整局可复盘数据。周期性调用本方法后，任何时刻中断都
        有账本可查；终局 finalize 会用完整数据覆盖同一目录。
        """
        if not self._recorder or not self._export_base_dir:
            return None
        return self._recorder.export_directory(self._export_base_dir)

    @property
    def run_id(self) -> str:
        return getattr(self._recorder, "run_id", "") if self._recorder else ""

    @property
    def exported_run_dir(self) -> Optional[str]:
        return self._exported_run_dir

    @property
    def recorder(self) -> Any:
        return self._recorder

    @property
    def tick_graphs(self) -> List[TraceGraph]:
        return list(self._tick_graphs)

    def get_trace_graph(self, tick: int) -> Optional[TraceGraph]:
        return next((graph for graph in self._tick_graphs if graph.tick == tick), None)

    def get_ancestors(self, node_id: str) -> List[TraceNode]:
        node = self._global_node_index.get(node_id)
        graph = self.get_trace_graph(node.tick) if node else None
        return graph.get_ancestors(node_id) if graph else []

    def query_by_agent(self, agent_id: str, tick: Optional[int] = None) -> List[TraceNode]:
        return [
            node for graph in self._tick_graphs
            if tick is None or graph.tick == tick
            for node in graph.nodes if node.agent_id == agent_id
        ]

    def query_by_type(self, node_type: str, tick: Optional[int] = None) -> List[TraceNode]:
        return [
            node for graph in self._tick_graphs
            if tick is None or graph.tick == tick
            for node in graph.nodes if node.node_type == node_type
        ]

    def query_by_action(self, action_id: str) -> List[TraceNode]:
        return [
            node for graph in self._tick_graphs for node in graph.nodes
            if node.payload_ref == action_id
        ]

    def validate_dag_rules(self, graph: TraceGraph) -> List[str]:
        incoming: Dict[str, List[TraceEdge]] = {}
        for edge in graph.edges:
            incoming.setdefault(edge.to_id, []).append(edge)
        violations = []
        for node in graph.nodes:
            sources = incoming.get(node.node_id, [])
            if node.node_type == "world_event" and node.source_refs and not sources:
                violations.append(f"world_event {node.node_id} 缺少事实来源边")
            if node.node_type == "settlement" and not sources:
                violations.append(f"settlement {node.node_id} 缺少世界事件来源边")
            if node.node_type == "director_plan" and node.source_refs and not sources:
                violations.append(f"director_plan {node.node_id} 缺少可信事实来源边")
        return violations

    def _build_tick_graph(
        self,
        tick: int,
        actions: List[Any],
        observations: List[Any],
        events: List[Any],
        settlements: List[Any],
        director_plan: Any,
        director_harness_trace: Any,
    ) -> TraceGraph:
        graph = TraceGraph(tick)
        for action in actions:
            action_id = str(_get(action, "action_id", "") or "")
            if action_id:
                graph.add_node(TraceNode(
                    node_id=f"action:{action_id}", node_type="world_action",
                    tick=tick, agent_id=_get(action, "actor_id"),
                    payload_ref=action_id,
                    source_refs=[str(_get(action, "harness_trace_ref", "") or "")],
                ))
        for observation in observations:
            observation_id = str(_get(observation, "observation_id", "") or "")
            if observation_id:
                graph.add_node(TraceNode(
                    node_id=f"observation:{observation_id}",
                    node_type="external_observation", tick=tick,
                    payload_ref=observation_id,
                    source_refs=[str(_get(observation, "source_uri", "") or "")],
                ))
        for event in events:
            event_id = str(_get(event, "event_id", "") or "")
            if not event_id:
                continue
            action_ref = str(_get(event, "source_action_ref", "") or "")
            event_node = f"event:{event_id}"
            graph.add_node(TraceNode(
                node_id=event_node, node_type="world_event", tick=tick,
                agent_id=_get(event, "actor_id"), payload_ref=event_id,
                source_refs=[action_ref] if action_ref else [],
            ))
            if graph.get_node(f"action:{action_ref}"):
                graph.add_edge(TraceEdge(
                    from_id=f"action:{action_ref}", to_id=event_node,
                    edge_type="caused_by",
                ))
            for ref in list(_get(event, "observation_refs", []) or []):
                if graph.get_node(f"observation:{ref}"):
                    graph.add_edge(TraceEdge(
                        from_id=f"observation:{ref}", to_id=event_node,
                        edge_type="grounded_by",
                    ))
        for record in settlements:
            record_id = str(_get(record, "settlement_id", "") or "")
            refs = list(_get(record, "source_event_refs", []) or [])
            if not record_id:
                continue
            node_id = f"settlement:{record_id}"
            subjects = list(_get(record, "subject_ids", []) or [])
            graph.add_node(TraceNode(
                node_id=node_id, node_type="settlement", tick=tick,
                agent_id=subjects[0] if subjects else None,
                payload_ref=record_id, source_refs=refs,
            ))
            for ref in refs:
                if graph.get_node(f"event:{ref}"):
                    graph.add_edge(TraceEdge(
                        from_id=f"event:{ref}", to_id=node_id,
                        edge_type="settled_by",
                    ))
        if director_plan:
            plan_id = str(_get(director_plan, "plan_id", "") or "")
            event_refs = list(_get(director_plan, "selected_event_refs", []) or [])
            record_refs = list(
                _get(director_plan, "selected_settlement_refs", []) or []
            )
            node_id = f"director:{plan_id}"
            graph.add_node(TraceNode(
                node_id=node_id, node_type="director_plan", tick=tick,
                payload_ref=plan_id, source_refs=[*event_refs, *record_refs],
            ))
            for ref in event_refs:
                if graph.get_node(f"event:{ref}"):
                    graph.add_edge(TraceEdge(
                        from_id=f"event:{ref}", to_id=node_id,
                        edge_type="rendered_from",
                    ))
            for ref in record_refs:
                if graph.get_node(f"settlement:{ref}"):
                    graph.add_edge(TraceEdge(
                        from_id=f"settlement:{ref}", to_id=node_id,
                        edge_type="rendered_from",
                    ))
            if director_harness_trace:
                trace_id = str(_get(director_harness_trace, "trace_id", "") or "")
                harness_id = f"director_harness:{trace_id}"
                graph.add_node(TraceNode(
                    node_id=harness_id, node_type="director_harness", tick=tick,
                    agent_id="os_director", payload_ref=trace_id,
                    source_refs=[*event_refs, *record_refs],
                ))
                graph.add_edge(TraceEdge(
                    from_id=harness_id, to_id=node_id, edge_type="produced_by",
                ))
        return graph
