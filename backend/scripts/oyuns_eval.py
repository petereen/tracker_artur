"""Opt-in live evaluation of the OYUNS agent; never runs in normal tests.

Runs a fixed set of multilingual prompts through the real agent turn
(context → model → tools → answer) as a given platform account, then checks
which tools were used and the answer language. Nothing is written: each turn's
transaction is rolled back, so task previews are not persisted.

Usage (inside the backend container, with the org key or OPENAI_API_KEY set):
    python -m scripts.oyuns_eval --email admin@company.mn
    python -m scripts.oyuns_eval --email member@company.mn --only tasks,rates
"""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass, replace

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.enterprise_deps import actor_from_account_id
from app.models.models import UserAccount
from app.services.ai_gateway import AIGateway
from app.services.assistant_text import detect_language


@dataclass(frozen=True)
class Case:
    key: str
    prompt: str
    language: str
    expect_tools: tuple[str, ...] = ()
    expect_route: str | None = None


CASES = (
    Case("tasks", "миний өнөөдрийн даалгаврууд юу вэ", "mn", ("oyuns_tasks_search",)),
    Case("tasks_ru", "Покажи мои просроченные задачи", "ru", ("oyuns_tasks_search",)),
    Case("rates", "USD-ийн ханш хэд вэ", "mn", ("oyuns_exchange_rate_get",)),
    Case("rates_en", "What is today's EUR to MNT rate?", "en", ("oyuns_exchange_rate_get",)),
    Case("delegate", "Батад маргааш 10 цагт борлуулалтын тайлан бэлдэх даалгавар өг", "mn", ("oyuns_tasks_prepare_create",), "task_preview"),
    Case("meeting", "би маргааш 16 цагаас хуралтай", "mn", (), "task_fast_path"),
    Case("worktime_now", "одоо хэн ажиллаж байна, хэн завсарлагатай вэ", "mn", ("oyuns_worktime_get",)),
    Case("worktime_week", "өнгөрсөн долоо хоногт хэн хамгийн их цаг ажилласан бэ", "mn", ("oyuns_worktime_get",)),
    Case("reports", "өчигдөр хэн тайлангаа илгээгээгүй вэ", "mn", ("oyuns_reports_search",)),
    Case("reports_content", "Сараа энэ долоо хоногт юу хийсэн бэ, тайлангаас нь хэлээч", "mn", ("oyuns_reports_search",)),
    Case("leave", "энэ сард хэн чөлөө авсан бэ", "mn", ("oyuns_hr_get",)),
    Case("crm", "Покажи просроченные CRM активности", "ru", ("oyuns_crm_search",)),
    Case("contracts", "дараагийн 30 хоногт дуусах гэрээнүүд", "mn", ("oyuns_contracts_search",)),
    Case("payroll", "энэ сарын цалингийн нийт дүн хэд вэ", "mn", ("oyuns_payroll_summary",)),
    Case("projects", "компанийн идэвхтэй төслүүд", "mn", ("oyuns_projects_search",)),
    Case("directory", "борлуулалтын хэлтэст хэн хэн ажилладаг вэ", "mn", ()),
    Case("knowledge", "компанийн амралтын журам юу гэж заасан байдаг вэ", "mn", ()),
    Case("capabilities", "What can you help me with?", "en"),
    Case("smalltalk", "сайн байна уу", "mn"),
    Case("multi", "миний даалгаврууд болон энэ долоо хоногт ажилласан цаг", "mn", ("oyuns_tasks_search", "oyuns_worktime_get")),
)


async def run(email: str, only: set[str] | None) -> int:
    gateway = AIGateway()
    failures = 0
    async with AsyncSessionLocal() as db:
        account = await db.scalar(select(UserAccount).where(UserAccount.email == email))
        if account is None:
            raise SystemExit(f"No account with email {email}")
        base_actor = await actor_from_account_id(account.id, db)
    for case in CASES:
        if only and case.key not in only:
            continue
        actor = replace(base_actor, channel="web", detected_language=detect_language(case.prompt).value)
        started = time.monotonic()
        async with AsyncSessionLocal() as db:
            try:
                response = await gateway.execute_turn(db, actor, [{"role": "user", "content": case.prompt}])
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"✗ {case.key}: {type(exc).__name__}: {exc}")
                failures += 1
                continue
            finally:
                await db.rollback()
        elapsed = int((time.monotonic() - started) * 1000)
        used = list(response.tools_used)
        problems = []
        if response.degraded:
            problems.append(f"degraded ({response.degraded_reason})")
        missing = [tool for tool in case.expect_tools if tool not in used]
        if missing and response.route != "task_preview":
            problems.append(f"missing tools {missing}")
        if case.expect_route and response.route != case.expect_route:
            problems.append(f"route {response.route} != {case.expect_route}")
        if detect_language(response.answer).value != case.language and len(response.answer) > 40:
            problems.append("answer language mismatch")
        failures += bool(problems)
        mark = "✗" if problems else "✓"
        print(f"{mark} {case.key} [{response.model}, {elapsed} ms, tools={used or '-'}] {'; '.join(problems)}")
        print("   " + response.answer.replace("\n", "\n   ")[:700])
    print(f"\n{failures} failing case(s)")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Platform account to run the prompts as")
    parser.add_argument("--only", help="Comma-separated case keys")
    args = parser.parse_args()
    only = {item.strip() for item in args.only.split(",")} if args.only else None
    raise SystemExit(1 if asyncio.run(run(args.email, only)) else 0)


if __name__ == "__main__":
    main()
