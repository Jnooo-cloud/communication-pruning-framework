"""Run an explicitly synthetic, zero-network demonstration."""

from decimal import Decimal
import json
from .audit import audit
from .configurations import bank
from .contracts import Response, TaskInput, Usage
from .execution import execute


def synthetic_agent(request):
    return Response(f"synthetic:{request.role}:{request.round}",
                    Usage(10, 3, Decimal("0"), "synthetic"))


def main():
    task = TaskInput("synthetic-001", "Which box contains the blue marble?",
                     ("The blue marble is in box A.", "Box B is empty."))
    reports = []
    for config in bank():
        trace = json.loads(json.dumps(execute(task, config, synthetic_agent)))
        reports.append({"configuration": config.config_id, **audit(trace, config)})
    print(json.dumps({"mode": "synthetic-only", "network_calls": 0,
                      "configurations": len(reports),
                      "agent_calls": sum(r["calls"] for r in reports),
                      "reports": reports}, indent=2))


if __name__ == "__main__":
    main()
