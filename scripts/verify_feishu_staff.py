"""验证五岗飞书 AI 员工 App 凭证."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matrixsolo.config import get_settings  # noqa: E402
from matrixsolo.feishu.client import FeishuClient  # noqa: E402


async def main() -> None:
    get_settings.cache_clear()
    client = FeishuClient()
    result = await client.verify_all_tokens()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = [k for k, v in result.items() if not v.get("ok")]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        raise SystemExit(1)
    print("\nAll 5 staff apps OK")


if __name__ == "__main__":
    asyncio.run(main())
