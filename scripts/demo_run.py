"""
MatrixSolo 本地一键演示：启动工作流并自动通过三道 HITL。
用法：
  python -m scripts.demo_run
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matrixsolo.orchestration import ProductionOrchestrator  # noqa: E402


async def main() -> None:
    orch = ProductionOrchestrator()
    state = await orch.start(trigger="demo", content_form="逐帧解说")
    print(f"started: {state.workflow_id} status={state.status.value}")
    print("topics:", [t.film_name for t in state.topics])
    state = await orch.auto_approve_demo(state.workflow_id)
    print(f"final status: {state.status.value}")
    if state.script:
        print("title:", state.script.selected_title)
        print("hook:", state.script.hook[:80])
    if state.render:
        print("final:", state.render.final_path, "md5:", state.render.md5)
    if state.distributions:
        print("platforms:", [(d.platform, d.title, str(d.scheduled_at)) for d in state.distributions])
    out = Path("data") / "demo_last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved:", out)


if __name__ == "__main__":
    asyncio.run(main())
