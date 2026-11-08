"""Internal service SLO/SLI definitions (REL-01: "document explicit
internal service SLO/SLI definitions"; acceptance criterion: "approved
SLO sheet contains workload assumptions").

`ServiceLevelObjective` is structured, testable DATA -- not free
prose an SLO "sheet" usually is -- so a caller can check whether an
actual measurement meets it in code, not by reading a paragraph.
`workload_assumption` and `approved_by` are both required with no
default, since an SLO with no stated workload assumption or no named
approver is not actually "approved" in any checkable sense.

Demonstrated against `experiments.latency_benchmark.LoadReport`
(REL-02, reused rather than reinvented): the SLO for the metadata API
states the SAME endpoint and the SAME workload shape (concurrency 8)
REL-02's own real load test exercises, and `slo_is_met` confirms a
genuine `LoadReport` from that real test satisfies it.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.experiments.latency_benchmark import LoadReport


@dataclass(frozen=True, slots=True)
class ServiceLevelObjective:
    service_name: str
    sli_description: str
    endpoint: str
    target_p95_seconds: float
    workload_assumption: str
    approved_by: str

    def __post_init__(self) -> None:
        if not self.service_name:
            raise ValueError("service_name must not be empty")
        if not self.sli_description:
            raise ValueError("sli_description must not be empty")
        if not self.endpoint:
            raise ValueError("endpoint must not be empty")
        if self.target_p95_seconds <= 0:
            raise ValueError("target_p95_seconds must be positive")
        if not self.workload_assumption:
            raise ValueError("workload_assumption must not be empty")
        if not self.approved_by:
            raise ValueError("approved_by must not be empty")


def slo_is_met(slo: ServiceLevelObjective, report: LoadReport) -> bool:
    if report.endpoint != slo.endpoint:
        raise ValueError(
            f"load report is for {report.endpoint!r}, this SLO is for {slo.endpoint!r} -- "
            "an SLO can only be checked against a report of its own endpoint"
        )
    return report.p95_seconds <= slo.target_p95_seconds
