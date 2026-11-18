"""Runs the golden set against one or more models and writes one result file per model.

    uv run python scripts/run_evals.py --model gpt-5-mini --model gpt-4.1-mini

Starts a PostgreSQL of its own in a container, so it needs Docker and nothing else that is
running. The model is reached with the endpoint and key in `.env`, or with the identity
of the process when there is no key, which is how the CI job runs it.

A run costs money. Before starting, the estimate of the run is added to what every earlier
run in `evals/runs` cost; past the cap, the run is refused.
"""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from testcontainers.community.postgres import PostgresContainer

from frontdesk.agent import prompts
from frontdesk.agent.graph import AgentDeps
from frontdesk.db.bootstrap import APP_ROLE, OWNER_ROLE, BootstrapPlan, bootstrap
from frontdesk.db.session import SessionFactory, create_engine, create_session_factory
from frontdesk.evals import budget, golden
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelProvider
from frontdesk.providers.prices import load_price_table
from frontdesk.seed import seed
from frontdesk.wiring import azure_openai_provider
from frontdesk.worker.handler import WorkerDeps

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
RUNS = REPO / "evals" / "runs"
PLAN = BootstrapPlan(database="frontdesk", owner_password="owner", app_password="app")  # noqa: S106
RETRIES_WHEN_INTERRUPTED = 2
WRITTEN_BY_A_CASE = (
    "owner_sessions, turn_steps, approval_requests, rule_findings, house_rules, handoffs, "
    "model_calls, messages, turns, inbound_events, conversations, bookings, schedule_blocks, "
    "customer_identities, customers"
)


class ModelAccess(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRONTDESK_", env_file=REPO / ".env", extra="ignore", env_parse_none_str=""
    )

    azure_openai_endpoint: str
    azure_openai_api_key: SecretStr | None = None


class SilentSender:
    """The channel of an eval run: the reply is read from the database, not delivered."""

    async def send(self, message: Any) -> Any:
        from frontdesk.channels.port import SendReceipt

        return SendReceipt(provider_message_id=f"eval-{message.message_id}")


def prompt_version() -> str:
    """A short hash of the prompts module, so a result names the prompts that produced it."""
    return hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()[:12]


def commit() -> str | None:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or None


def migrate(owner_url: str) -> None:
    config = Config(BACKEND / "alembic.ini")
    config.set_main_option("sqlalchemy.url", owner_url)
    command.upgrade(config, "head")


async def run_model(
    sessions: SessionFactory,
    superuser_dsn: str,
    provider: ModelProvider,
    model: str,
    chosen: golden.GoldenSet,
) -> dict[str, Any]:
    agent = AgentDeps(
        sessions=sessions,
        provider=provider,
        model=model,
        ledger=ModelLedger(sessions, load_price_table()),
    )

    def worker(now: dt.datetime) -> WorkerDeps:
        return WorkerDeps(
            sessions=sessions, agent=agent, senders={"webchat": SilentSender()}, clock=lambda: now
        )

    async def reset() -> None:
        async with await psycopg.AsyncConnection.connect(
            superuser_dsn, dbname=PLAN.database, autocommit=True
        ) as connection:
            await connection.execute(f"truncate {WRITTEN_BY_A_CASE} cascade")

    environment = golden.Environment(sessions=sessions, worker=worker, reset=reset)
    results = []
    for case in chosen.cases:
        result = await golden.run_case(environment, case, chosen.now)
        for _ in range(RETRIES_WHEN_INTERRUPTED):
            if not golden.interrupted(result):
                break
            await asyncio.sleep(15)
            result = await golden.run_case(environment, case, chosen.now)
        mark = "pass" if result.passed else "FAIL"
        print(f"  {mark}  {case.id}" + ("" if result.passed else f"  {result.failures}"))
        results.append(result)
    return {
        "golden_version": chosen.version,
        "model": model,
        "provider": provider.name,
        "prompt_version": prompt_version(),
        "price_table_version": load_price_table().version,
        "commit": commit(),
        "ran_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "totals": golden.summary(results),
        "cases": golden.as_document(results),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", action="append", required=True, help="deployment to run")
    parser.add_argument("--cases", type=Path, default=REPO / "evals" / "golden" / "cases.json")
    parser.add_argument("--only", help="run only the cases of this category")
    parser.add_argument("--cap-usd", type=float, default=5.0, help="total the runs may cost")
    parser.add_argument("--no-save", action="store_true", help="do not write result files")
    parser.add_argument(
        "--out",
        type=Path,
        help="write the result of the one model here, outside the committed history of runs",
    )
    arguments = parser.parse_args()

    chosen = golden.load(arguments.cases)
    if arguments.only:
        cases = [case for case in chosen.cases if case.category == arguments.only]
        chosen = golden.GoldenSet(chosen.version, chosen.now, cases)
    turns = sum(len(case.turns) for case in chosen.cases)
    cap = round(arguments.cap_usd * 1_000_000)
    fits, spent, expected = budget.allows(RUNS, arguments.model, turns, cap)
    print(f"spent so far {spent} micro-USD, this run about {expected}, cap {cap}")
    if not fits:
        print("refused: the estimate of this run passes what is left of the budget")
        return 2

    access = ModelAccess()
    provider = azure_openai_provider(access.azure_openai_endpoint, access.azure_openai_api_key)
    # A database that lives for this run only, on this machine.
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",  # noqa: S106  not a secret: the container dies with the run
    ) as db:
        host, port = db.get_container_host_ip(), int(db.get_exposed_port(5432))
        superuser_dsn = f"postgresql://postgres:postgres@{host}:{port}/postgres"
        bootstrap(superuser_dsn, PLAN)
        migrate(
            f"postgresql+psycopg://{OWNER_ROLE}:{PLAN.owner_password}@{host}:{port}/{PLAN.database}"
        )
        engine = create_engine(
            f"postgresql+psycopg://{APP_ROLE}:{PLAN.app_password}@{host}:{port}/{PLAN.database}"
        )
        sessions = create_session_factory(engine)
        await seed(sessions)
        try:
            for model in arguments.model:
                print(f"{model}: {len(chosen.cases)} cases")
                run = await run_model(sessions, superuser_dsn, provider, model, chosen)
                totals = run["totals"]
                print(
                    f"  {totals['passed']}/{totals['cases']} passed, "
                    f"{totals['cost_microusd']} micro-USD, "
                    f"median model time per turn {totals['model_ms_per_turn_p50']} ms"
                )
                if arguments.out:
                    arguments.out.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
                    print(f"  written to {arguments.out}")
                elif not arguments.no_save:
                    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
                    path = RUNS / f"{stamp}-{model}.json"
                    path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
                    print(f"  written to {path.relative_to(REPO)}")
        finally:
            await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
