"""Run the unchanged Z55 replay (run_z55.py replay --folder F [--limit N]) under the V3 network lock.

Use the GPTSwarm interpreter: runs/Z38-QSEM-001/provision/python/bin/python3.12.
Without --record, run_z55.replay writes only into F (checked in run_z55.py: guard_write, replay()).
"""
import sys

sys.dont_write_bytecode = True

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402
import runpy  # noqa: E402

V3 = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("z56_netguard", V3 / "netguard.py")
netguard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(netguard)
netguard.install()

TARGET = V3.parents[1] / "Z55-GPTSWARM-DEMO-001" / "run_z55.py"
folder = Path(sys.argv[1]).resolve()
extra = sys.argv[2:]
if "--record" in extra:
    raise SystemExit("--record would write into the Z55 folder")
sys.argv = [str(TARGET), "replay", "--folder", str(folder), *extra]
try:
    runpy.run_path(str(TARGET), run_name="__main__")
finally:
    netguard.dump(folder.parent / (folder.name + "-network.json"))
