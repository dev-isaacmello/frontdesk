"""KB-1 and what retrieval adds to a turn: the tenant's own knowledge, and only its own."""

from sqlalchemy import text

from frontdesk.agent.graph import AgentDeps, run_turn
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.knowledge import put_chunk, search
from frontdesk.providers.embeddings import Embedded, HashingEmbedder
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelResponse, ModelUnavailableError
from frontdesk.providers.scripted import ScriptedProvider, says
from frontdesk.seed import ARENA, BARBERSHOP
from tests.support import IN_SCOPE, PRICES, start_turn

EMBEDDER = HashingEmbedder()


def agent(sessions: SessionFactory, *script: ModelResponse) -> tuple[AgentDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = AgentDeps(
        sessions=sessions,
        provider=provider,
        model="scripted",
        ledger=ModelLedger(sessions, PRICES),
        embedder=EMBEDDER,
    )
    return deps, provider


async def vector_of(words: str) -> list[float]:
    return (await EMBEDDER.embed([words])).vectors[0]


async def test_kb_1_a_search_reads_only_the_chunks_of_its_tenant(sessions: SessionFactory) -> None:
    query = await vector_of("estacionamento")

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        barbershop = await search(session, query, EMBEDDER.model, limit=20, max_distance=2)
    async with tenant_transaction(sessions, ARENA.id) as session:
        arena = await search(session, query, EMBEDDER.model, limit=20, max_distance=2)

    assert {chunk.title for chunk in barbershop} == {title for title, _ in BARBERSHOP.knowledge}
    assert {chunk.title for chunk in arena} == {title for title, _ in ARENA.knowledge}
    assert barbershop[0].body.startswith("Não temos estacionamento próprio")
    assert arena[0].body.startswith("O estacionamento é gratuito")


async def test_kb_1_asking_for_another_tenant_by_name_returns_nothing(
    sessions: SessionFactory,
) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        rows = await session.execute(
            text("select title from kb_chunks where tenant_id = :other"), {"other": ARENA.id}
        )

    assert rows.all() == []


async def test_kb_vectors_of_another_model_are_not_compared(sessions: SessionFactory) -> None:
    query = await vector_of("garantia do serviço")
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await put_chunk(
            session, BARBERSHOP.id, "Garantia", "Garantia do serviço.", query, "another-model"
        )

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        found = await search(session, query, EMBEDDER.model, limit=20, max_distance=2)
        await session.execute(text("delete from kb_chunks where embedding_model = 'another-model'"))

    assert "Garantia" not in {chunk.title for chunk in found}


async def test_kb_what_is_close_to_the_question_reaches_the_planner(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("Tem um estacionamento pago ao lado."))

    await run_turn(deps, await start_turn(sessions, "tem estacionamento aí?"))

    assert "estacionamento pago ao lado, na mesma quadra" in provider.requests[-1].system


async def test_kb_1_the_knowledge_of_one_tenant_does_not_reach_another_through_a_turn(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("Temos estacionamento para clientes."))

    await run_turn(deps, await start_turn(sessions, "tem estacionamento aí?", tenant=ARENA))

    assert "gratuito para clientes" in provider.requests[-1].system
    assert "estacionamento pago ao lado" not in provider.requests[-1].system


async def test_grd_2_a_number_from_the_knowledge_base_can_be_stated(
    sessions: SessionFactory,
) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Ficamos na Rua dos Andradas, 1200, no Centro."))

    result = await run_turn(deps, await start_turn(sessions, "qual o endereço de vocês?"))

    assert result.outcome == "replied"


async def test_pol_1_a_free_thing_the_owner_wrote_in_the_knowledge_base_can_be_repeated(
    sessions: SessionFactory,
) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Sim, o estacionamento é gratuito para clientes."))

    result = await run_turn(
        deps, await start_turn(sessions, "tem estacionamento aí?", tenant=ARENA)
    )

    assert result.outcome == "replied"


async def test_kb_a_turn_goes_on_without_knowledge_when_the_embedder_is_down(
    sessions: SessionFactory,
) -> None:
    class Down:
        name, model, max_distance = "offline", "offline-hashing", 0.9

        async def embed(self, _texts: list[str]) -> Embedded:
            raise ModelUnavailableError("embedding model is down")

    healthy, provider = agent(sessions, IN_SCOPE, says("Oi! Como posso ajudar?"))
    deps = AgentDeps(
        sessions=sessions,
        provider=healthy.provider,
        model=healthy.model,
        ledger=healthy.ledger,
        embedder=Down(),
    )

    result = await run_turn(deps, await start_turn(sessions, "oi, tem estacionamento?"))

    assert result.outcome == "replied"
    assert "<informacoes>" not in provider.requests[-1].system


async def test_cst_1_the_embedding_of_a_turn_is_in_the_ledger(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Oi! Como posso ajudar?"))

    await run_turn(deps, await start_turn(sessions, "oi, tem estacionamento?"))

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        nodes = await session.execute(text("select node, model from model_calls order by id"))
    assert ("retrieve", "offline-hashing") in nodes.all()
