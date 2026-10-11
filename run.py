"""NEXA Desktop Assistant Entrypoint.

Launches the native Windows desktop application shell.
Usage:
    .\venv\Scripts\python.exe run.py
"""
import atexit
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.main import main

if __name__ == "__main__":
    agent_proc = None
    if "--with-agent" in sys.argv:
        sys.argv.remove("--with-agent")
        print("[NEXA] Spawning LiveKit Voice Agent worker in background...")
        python_exe = sys.executable
        agent_proc = subprocess.Popen(
            [python_exe, "backend/agent.py", "dev"],
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
        )

        def _cleanup_agent():
            if agent_proc and agent_proc.poll() is None:
                print("[NEXA] Terminating background LiveKit Agent...")
                agent_proc.terminate()
                try:
                    agent_proc.wait(timeout=8)
                except Exception:
                    print("[NEXA] Forcibly killing unresponsive LiveKit Agent...")
                    try:
                        agent_proc.kill()
                    except Exception:
                        pass

        atexit.register(_cleanup_agent)

    ret = main()
    if agent_proc:
        _cleanup_agent()
    sys.exit(ret)
