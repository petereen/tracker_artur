"""Opt-in smoke test for the production AI gateway; never runs in normal tests."""
from __future__ import annotations

import asyncio
import os

from app.core.database import AsyncSessionLocal
from app.services.ai_gateway import AIGateway, GatewayRequest


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required; no live request was sent")
    async with AsyncSessionLocal() as db:
        answer = await AIGateway().respond(db, GatewayRequest(text="Reply with the word ready.", history=[], channel="smoke", language_hint="en"))
        print({"model": answer.model, "route": answer.route, "answer": answer.answer})


if __name__ == "__main__":
    asyncio.run(main())
