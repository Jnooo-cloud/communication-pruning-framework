"""Fresh process per native synthetic graph case, Python network audit guard."""
import sys

def deny_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "http.client.connect", "urllib.Request"):
        raise RuntimeError("Z31 prohibits network calls during synthetic execution")

sys.addaudithook(deny_network)
import asyncio
from communication_pruning.gptswarm_probe import run_case
result = asyncio.run(run_case(sys.argv[1], sys.argv[2]))
print(result)
assert not any(name.startswith("swarm.llm") for name in sys.modules), "unplanned model backend imported"
