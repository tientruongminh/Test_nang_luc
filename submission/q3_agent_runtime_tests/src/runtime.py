from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class BranchStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class GraphDefinition:
    graph_id: str
    version: int
    required_fan_in_branches: tuple[str, ...]

    @property
    def pinned_ref(self) -> str:
        return f"{self.graph_id}@v{self.version}"


@dataclass
class AgentRun:
    run_id: str
    tenant_id: str
    graph_ref: str
    branch_status: dict[str, BranchStatus] = field(default_factory=dict)


class AgentRuntimeSimulator:
    """Small deterministic simulator for the runtime contracts in Câu 3.

    It models only the safety-critical pieces needed by the submission:
    graph pinning, tenant isolation, and fan-in behavior when one branch is
    missing or still UNKNOWN.
    """

    def __init__(self) -> None:
        self._active_graphs: dict[str, GraphDefinition] = {}
        self._runs: dict[str, AgentRun] = {}

    def activate_graph(self, tenant_id: str, graph: GraphDefinition) -> None:
        self._active_graphs[tenant_id] = graph

    def start_run(self, tenant_id: str, run_id: str) -> AgentRun:
        graph = self._active_graphs[tenant_id]
        run = AgentRun(
            run_id=run_id,
            tenant_id=tenant_id,
            graph_ref=graph.pinned_ref,
            branch_status={branch: BranchStatus.UNKNOWN for branch in graph.required_fan_in_branches},
        )
        self._runs[run_id] = run
        return run

    def resume_run(self, requester_tenant_id: str, run_id: str) -> AgentRun:
        run = self._runs[run_id]
        if run.tenant_id != requester_tenant_id:
            raise PermissionError("cross_tenant_resume_denied")
        return run

    def record_branch(self, tenant_id: str, run_id: str, branch: str, status: BranchStatus | str) -> None:
        run = self.resume_run(tenant_id, run_id)
        if branch not in run.branch_status:
            raise KeyError(f"unknown_branch:{branch}")
        run.branch_status[branch] = BranchStatus(status)

    def can_fan_in(self, tenant_id: str, run_id: str, observed: Mapping[str, BranchStatus | str] | None = None) -> bool:
        run = self.resume_run(tenant_id, run_id)
        statuses = dict(run.branch_status)
        if observed:
            statuses.update({branch: BranchStatus(status) for branch, status in observed.items()})
        required = self._required_branches_for_pinned_run(run)
        return all(statuses.get(branch, BranchStatus.UNKNOWN) == BranchStatus.SUCCEEDED for branch in required)

    def _required_branches_for_pinned_run(self, run: AgentRun) -> tuple[str, ...]:
        for graph in self._active_graphs.values():
            if graph.pinned_ref == run.graph_ref:
                return graph.required_fan_in_branches
        return tuple(run.branch_status)

