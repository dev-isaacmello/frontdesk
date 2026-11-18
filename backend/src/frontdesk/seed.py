"""Two fictional tenants with different services, prices, hours and resources.

Ids are derived from names, so seeding twice changes nothing and tests can name the
rows they expect.
"""

from dataclasses import dataclass
from datetime import time
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import (
    BusinessHours,
    ChannelAccount,
    KbChunk,
    Resource,
    Service,
    ServicePrice,
    ServiceResource,
    Tenant,
    User,
)
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.knowledge import put_chunk
from frontdesk.domain.owners import hash_password
from frontdesk.providers.embeddings import Embedder, HashingEmbedder

_NAMESPACE = UUID("6f1d3c52-7a0e-4b57-9d5e-2f0c8a41b6e3")
_MIDNIGHT = time(0, 0)


@dataclass(frozen=True)
class ServiceSeed:
    name: str
    duration_minutes: int
    prices: tuple[tuple[time, int], ...]
    resources: tuple[str, ...]


@dataclass(frozen=True)
class TenantSeed:
    slug: str
    name: str
    timezone: str
    slot_minutes: int
    resource_kind: str
    resources: tuple[str, ...]
    open_weekdays: tuple[int, ...]
    opens: time
    closes: time
    services: tuple[ServiceSeed, ...]
    late_change_minutes: int | None = None
    """Notice below which cancelling or moving a booking needs the owner's approval."""
    knowledge: tuple[tuple[str, str], ...] = ()
    """What the owner knows and the catalog does not: a title and a short text each."""

    @property
    def id(self) -> UUID:
        return uuid5(_NAMESPACE, self.slug)

    @property
    def owner_email(self) -> str:
        return f"dono@{self.slug}.example"

    def resource_id(self, name: str) -> UUID:
        return uuid5(self.id, f"resource:{name}")

    def service_id(self, name: str) -> UUID:
        return uuid5(self.id, f"service:{name}")


BARBERSHOP = TenantSeed(
    slug="navalha",
    name="Barbearia Navalha",
    timezone="America/Sao_Paulo",
    slot_minutes=30,
    resource_kind="professional",
    resources=("Caio", "Renan"),
    open_weekdays=(2, 3, 4, 5, 6),
    opens=time(9, 0),
    closes=time(19, 0),
    services=(
        ServiceSeed("Corte", 30, ((_MIDNIGHT, 4500),), ("Caio", "Renan")),
        ServiceSeed("Barba", 20, ((_MIDNIGHT, 3000),), ("Caio", "Renan")),
        ServiceSeed("Corte e barba", 50, ((_MIDNIGHT, 7000),), ("Caio", "Renan")),
    ),
    late_change_minutes=180,
    knowledge=(
        ("Endereço", "Ficamos na Rua dos Andradas, 1200, no Centro Histórico de Porto Alegre."),
        (
            "Estacionamento",
            "Não temos estacionamento próprio. Há um estacionamento pago ao lado, na mesma quadra.",
        ),
        (
            "Formas de pagamento",
            "Aceitamos Pix, cartão de débito e cartão de crédito. Não aceitamos cheque.",
        ),
        (
            "Atraso",
            "A tolerância de atraso é de 10 minutos. Depois disso o horário pode ser passado "
            "para outro cliente.",
        ),
        ("Crianças", "Atendemos crianças a partir de 5 anos, acompanhadas de um responsável."),
        ("Produtos à venda", "Vendemos pomada, óleo para barba e shampoo na recepção."),
        ("Café e wi-fi", "Temos café, água e wi-fi para os clientes enquanto esperam."),
        (
            "Cancelamento em cima da hora",
            "Para cancelar ou mudar um horário com menos de 3 horas de antecedência, o pedido "
            "passa pelo responsável da barbearia.",
        ),
    ),
)

ARENA = TenantSeed(
    slug="ponto-final",
    name="Arena Ponto Final",
    timezone="America/Sao_Paulo",
    slot_minutes=60,
    resource_kind="court",
    resources=("Quadra Society", "Quadra de Areia"),
    open_weekdays=(1, 2, 3, 4, 5, 6, 7),
    opens=time(8, 0),
    closes=time(23, 0),
    services=(
        ServiceSeed(
            "Society (1 hora)",
            60,
            ((_MIDNIGHT, 12000), (time(18, 0), 18000)),
            ("Quadra Society",),
        ),
        ServiceSeed(
            "Areia (1 hora)",
            60,
            ((_MIDNIGHT, 8000), (time(18, 0), 11000)),
            ("Quadra de Areia",),
        ),
    ),
    knowledge=(
        ("Endereço", "Ficamos na Avenida Ipiranga, 5300, no Jardim Botânico, em Porto Alegre."),
        (
            "Calçado",
            "Traga chuteira society ou tênis. Não é permitido jogar com chuteira de trava alta.",
        ),
        ("Coletes e bola", "Emprestamos coletes e uma bola para cada reserva."),
        (
            "Chuva",
            "A quadra de areia fecha em caso de chuva forte. A quadra society é coberta e "
            "funciona normalmente.",
        ),
        (
            "Vestiário",
            "Temos vestiário com chuveiro quente e armários. Traga o seu cadeado.",
        ),
        ("Estacionamento", "O estacionamento é gratuito para clientes e tem 40 vagas."),
        ("Bar", "O bar abre junto com as quadras e serve bebidas e lanches."),
        (
            "Aniversários",
            "Fazemos reserva para aniversários e confraternizações. Fale com a equipe para "
            "combinar os detalhes.",
        ),
    ),
)

TENANTS = (BARBERSHOP, ARENA)


async def seed(
    factory: SessionFactory,
    owner_password: str | None = None,
    embedder: Embedder | None = None,
) -> None:
    """Creates the fictional tenants, and an owner account for each when a password is given.

    The password is the same for both demo owners and comes from the environment of the
    setup. Without one there are no owner accounts and the panel cannot be signed in to.
    The knowledge base is embedded with the given embedder, or with the offline one.
    """
    embedder = embedder or HashingEmbedder()
    for tenant in TENANTS:
        async with tenant_transaction(factory, tenant.id) as session:
            row = await session.get(Tenant, tenant.id)
            if row is None:
                await _add_tenant(session, tenant)
            else:
                # Settings added after a database was first seeded reach it here.
                row.late_change_minutes = tenant.late_change_minutes
            if owner_password is not None:
                await _add_owner(session, tenant, owner_password)
        await _embed_knowledge(factory, tenant, embedder)


async def _embed_knowledge(factory: SessionFactory, tenant: TenantSeed, embedder: Embedder) -> None:
    """Stores the tenant's knowledge, embedding only what is new or was embedded otherwise."""
    async with tenant_transaction(factory, tenant.id) as session:
        current = {
            (title, body)
            for title, body in await session.execute(
                select(KbChunk.title, KbChunk.body).where(KbChunk.embedding_model == embedder.model)
            )
        }
    stale = [entry for entry in tenant.knowledge if entry not in current]
    if not stale:
        return
    embedded = await embedder.embed([f"{title}. {body}" for title, body in stale])
    async with tenant_transaction(factory, tenant.id) as session:
        for (title, body), vector in zip(stale, embedded.vectors, strict=True):
            await put_chunk(session, tenant.id, title, body, vector, embedder.model)


async def _add_owner(session: AsyncSession, tenant: TenantSeed, password: str) -> None:
    known = await session.scalar(select(User.id).where(User.email == tenant.owner_email))
    if known is None:
        session.add(
            User(
                tenant_id=tenant.id,
                email=tenant.owner_email,
                name=f"Responsável, {tenant.name}",
                password_hash=hash_password(password),
            )
        )


async def _add_tenant(session: AsyncSession, tenant: TenantSeed) -> None:
    # The mappings declare no relationships, so rows are flushed parent first by hand.
    session.add(
        Tenant(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            timezone=tenant.timezone,
            slot_minutes=tenant.slot_minutes,
            late_change_minutes=tenant.late_change_minutes,
        )
    )
    await session.flush()
    # The web chat of a tenant is addressed by its slug.
    session.add(ChannelAccount(tenant_id=tenant.id, channel="webchat", external_id=tenant.slug))
    session.add_all(
        BusinessHours(
            tenant_id=tenant.id, weekday=weekday, opens=tenant.opens, closes=tenant.closes
        )
        for weekday in tenant.open_weekdays
    )
    session.add_all(
        Resource(
            id=tenant.resource_id(name),
            tenant_id=tenant.id,
            name=name,
            kind=tenant.resource_kind,
        )
        for name in tenant.resources
    )
    session.add_all(
        Service(
            id=tenant.service_id(service.name),
            tenant_id=tenant.id,
            name=service.name,
            duration_minutes=service.duration_minutes,
        )
        for service in tenant.services
    )
    await session.flush()
    for service in tenant.services:
        service_id = tenant.service_id(service.name)
        session.add_all(
            ServicePrice(
                tenant_id=tenant.id,
                service_id=service_id,
                starts_at=starts_at,
                price_cents=price_cents,
            )
            for starts_at, price_cents in service.prices
        )
        session.add_all(
            ServiceResource(
                tenant_id=tenant.id,
                service_id=service_id,
                resource_id=tenant.resource_id(resource),
            )
            for resource in service.resources
        )
