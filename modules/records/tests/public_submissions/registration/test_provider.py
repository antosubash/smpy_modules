"""The ``records:registration`` provider: events asks it about targets and registrants."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sm_events.contracts.extensions import RegistrationContext, RegistrationTargetError
from sm_events.core.tenancy import tenant_scope
from sm_records.integrations.events import registration_provider as provider_module

from tests.support.app_harness import ADMIN, roles
from tests.support.public_submissions_support import create
from tests.support.registration_http import (
    TYPE,
    record_url,
    reg_config,
    reg_fields,
    register,
    regs,
    seed_event,
    single_opt_in,
)

pytestmark = pytest.mark.usefixtures("reg_site")


def provider():
    return provider_module.provider()


async def ctx(site):
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            yield RegistrationContext("default", db)


def viewer(user, role, *perms):
    from sm_events.contracts.extensions import SourceViewer

    return SourceViewer(user, (role,) if role else (), frozenset(perms), None)


VIEW, EDIT, MANAGE = "records.view", "records.edit", "records.manage_types"
ADMIN_V = viewer("a", "admin", VIEW, EDIT, MANAGE)
EDITOR_V = viewer("e", "records-editor", VIEW, EDIT)
VIEWER_V = viewer("v", "records-viewer", VIEW)
NOBODY_V = viewer("n", None)


async def check(site, target, who=ADMIN_V):
    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            return await provider().check_target(RegistrationContext("default", db, who), target)


async def test_check_target(reg_site):
    info = await check(reg_site, TYPE)
    assert info.label == "Event_Registrations" or info.label
    assert info.admin_url == f"/admin/records/{TYPE}" and info.attendees_url.startswith(
        info.admin_url
    )
    await create(reg_site, "contact")
    for bad in ("nope", "contact", "", "x" * 300):
        with pytest.raises(RegistrationTargetError):
            await check(reg_site, bad)


async def test_another_tenants_type_is_unknown(reg_site):
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            with pytest.raises(RegistrationTargetError):
                # the context names a tenant that does not own the type
                await provider().check_target(RegistrationContext("other", db, ADMIN_V), TYPE)


async def test_recipients(reg_site):
    event = await seed_event(reg_site.db_state, uid="many@x", registration_capacity=10)
    await register(reg_site, "pending@example.org", name="Pat", event=event)
    await single_opt_in(reg_site)
    for email, name in (("ok", "Olga"), ("cancelled", "Carl"), ("trashed", "Tim")):
        extra = {"locale": "de"} if email == "ok" else {}
        await register(
            reg_site, f"{email}@example.org", name=name, consent=True, event=event, **extra
        )
    by_email = {r["data"]["sm_email"]: r for r in await regs(reg_site)}
    await reg_site.post(
        record_url(by_email["cancelled@example.org"]["uuid"], "/submission/cancel"),
        headers=roles(ADMIN),
    )
    await reg_site.delete(record_url(by_email["trashed@example.org"]["uuid"]), headers=roles(ADMIN))
    holders = [str(uuid.UUID(r["uuid"])) for r in by_email.values()] + [str(uuid.uuid4())]
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            got = await provider().recipients(RegistrationContext("default", db), holders)
    ok = str(uuid.UUID(by_email["ok@example.org"]["uuid"]))
    assert list(got) == [ok]
    who = got[ok]
    assert (who.email, who.name, who.locale) == ("ok@example.org", "Olga", "de")


async def test_the_registrants_default_language(reg_site):
    await single_opt_in(reg_site)
    await register(reg_site, "x@example.org", consent=True)
    (record,) = await regs(reg_site)
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            got = await provider().recipients(
                RegistrationContext("default", db), [str(uuid.UUID(record["uuid"]))]
            )
    assert next(iter(got.values())).locale == "en"


async def test_events_calls_it_through_its_own_runner(reg_site):
    from sm_events.registration import provider_call

    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            await db.connection()
            info = await provider_call.check_target(
                provider(), db=db, tenant_id="default", target=TYPE, viewer=ADMIN_V
            )
            assert info.admin_url == f"/admin/records/{TYPE}"
            from sm_events.core.errors_registration import UnknownRegistrationTarget

            with pytest.raises(UnknownRegistrationTarget):
                await provider_call.check_target(
                    provider(), db=db, tenant_id="default", target="no"
                )


def test_the_extension_file_registers_it():
    from sm_records import events_extensions

    seen = SimpleNamespace(sources=[], providers=[])
    registry = SimpleNamespace(
        add_source=seen.sources.append, add_registration_provider=seen.providers.append
    )
    events_extensions.register(registry)
    assert [p.id for p in seen.providers] == ["records:registration"]
    assert seen.providers[0].label_key == "records.events.registration.label"


async def test_an_editor_without_rights_gets_the_missing_forms_refusal(reg_site):
    await create(reg_site, "restricted", fields=reg_fields(), config=reg_config(),
                 allowed_roles=["records-editor"])  # fmt: skip
    refusals = []
    for who, target in (
        (ADMIN_V, "restricted"),  # admin is not on the allowed roles
        (VIEWER_V, TYPE),  # may view, may not configure types
        (NOBODY_V, TYPE),
        (None, TYPE),  # a worker is not an editor
        (ADMIN_V, "no_such_form"),
    ):
        with pytest.raises(RegistrationTargetError) as caught:
            await check(reg_site, target, who)
        refusals.append(str(caught.value))
    assert len(set(refusals)) == 1 and "restricted" not in refusals[0]


async def test_list_and_the_provider_agree_for_every_user_and_type(reg_site):
    """One rule: the console's list shows exactly what ``can_read`` reads, and ``check_target``
    admits exactly those who may also configure types."""
    from tests.support.harness_auth import ROLE_EDITOR, ROLE_VIEWER

    await create(reg_site, "restricted", fields=reg_fields(), config=reg_config(),
                 allowed_roles=[ROLE_EDITOR])  # fmt: skip
    people = {
        "admin": (roles(ADMIN), ADMIN_V),
        "editor": (roles(ROLE_EDITOR), EDITOR_V),
        "viewer": (roles(ROLE_VIEWER), VIEWER_V),
    }
    for name, (headers, who) in people.items():
        listed = {
            r["key"]
            for r in (await reg_site.get("/api/records/registration-forms", headers=headers)).json()
        }
        for key in (TYPE, "restricted"):
            with tenant_scope("default"):
                async with reg_site.db_state.session_factory() as db:
                    ctx = RegistrationContext("default", db, who)
                    readable = await provider().can_read(ctx, key)
                    try:
                        await provider().check_target(ctx, key)
                        usable = True
                    except RegistrationTargetError:
                        usable = False
            assert readable == (key in listed), (name, key)
            assert usable == (readable and MANAGE in who.permissions), (name, key)
    nobody = RegistrationContext("default", None, None)  # type: ignore[arg-type]
    assert nobody.viewer is None
