"""Deterministic value generation, driven entirely by ``random.Random(seed)``.

Two kinds of value live in every generated record: **random** ones (a name, a
city, a price) that come straight out of ``rng``, and **unique** ones (an
email, a SKU, an order number) that must never collide across repeated runs
of the seeder against the same database. The latter are built from a
monotonic ``seq`` counter the caller derives from the type's current record
count (see ``runner.py``), never from ``rng`` alone — two runs with the same
``--seed`` would otherwise regenerate the same email on top of one that
already exists.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sm_records.seed import data


def random_date(rng: random.Random, start_year: int, end_year: int) -> date:
    start = date(start_year, 1, 1).toordinal()
    end = date(end_year, 12, 31).toordinal()
    return date.fromordinal(rng.randint(start, end))


def random_datetime(rng: random.Random, start_year: int, end_year: int) -> datetime:
    """Aware UTC — ``to_datetime`` (``schema/_builders.py``) refuses naive
    values outright."""
    day = random_date(rng, start_year, end_year)
    seconds = rng.randint(0, 24 * 60 * 60 - 1)
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(seconds=seconds)


def _slugish(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def company_name(rng: random.Random) -> str:
    prefix = rng.choice(data.COMPANY_PREFIXES)
    word = rng.choice(data.COMPANY_WORDS)
    legal = rng.choice(data.COMPANY_LEGAL_SUFFIXES)
    return f"{prefix} {word} {legal}"


def gen_company(rng: random.Random, seq: int) -> tuple[dict[str, Any], str]:
    """Returns ``(payload, slug)`` — the slug is explicit (not derived from
    ``slug_field``) because two companies can land on the same name from a
    small word pool; ``seq`` keeps every slug distinct regardless."""
    name = company_name(rng)
    city, state = rng.choice(data.CITIES)
    payload = {
        "name": name,
        "state": state,
        "city": city,
        "founded": random_date(rng, 1975, 2023),
        "employees": rng.randint(2, 50_000),
        "annual_revenue": round(rng.uniform(50_000, 5_000_000_000), 2),
        "website": f"https://www.{_slugish(name)}.com",
        "is_public": rng.random() < 0.2,
        "description": (
            f"{name} is a {rng.choice(data.INDUSTRY_BLURBS)} company based in {city}, {state}."
        ),
    }
    return payload, f"{_slugish(name)}-{seq}"


def gen_contact(rng: random.Random, seq: int, *, company_uuid: str | None) -> dict[str, Any]:
    first = rng.choice(data.FIRST_NAMES)
    last = rng.choice(data.LAST_NAMES)
    domain = rng.choice(data.EMAIL_DOMAINS)
    email = f"{first.lower()}.{last.lower()}.{seq}@{domain}"
    payload: dict[str, Any] = {
        "first_name": first,
        "last_name": last,
        "email": email,
        "title": rng.choice(data.JOB_TITLES),
        "phone": (f"({rng.randint(200, 989)}) {rng.randint(200, 989)}-{rng.randint(1000, 9999)}"),
        "birthday": random_date(rng, 1955, 2004),
        "newsletter": rng.random() < 0.55,
        "notes": f"Prefers contact by {'email' if rng.random() < 0.5 else 'phone'}.",
    }
    if company_uuid is not None:
        payload["company"] = {"type": "company", "uuid": company_uuid}
    return payload


def gen_product(rng: random.Random, seq: int) -> dict[str, Any]:
    adjective = rng.choice(data.PRODUCT_ADJECTIVES)
    noun = rng.choice(data.PRODUCT_NOUNS)
    name = f"{adjective} {noun}"
    tags = rng.sample(data.TAG_POOL, k=rng.randint(1, 4))
    return {
        "sku": f"SKU-{seq:06d}",
        "name": name,
        "category": rng.choice(data.PRODUCT_CATEGORIES),
        "price": round(rng.uniform(4.99, 2499.99), 2),
        "in_stock": rng.random() < 0.85,
        "tags": tags,
        "weight_lbs": round(rng.uniform(0.1, 85.0), 2),
        "specs": {
            "color": rng.choice(["black", "white", "gray", "blue", "red", "green"]),
            "material": rng.choice(["plastic", "aluminum", "steel", "wood", "fabric"]),
            "warranty_years": rng.randint(0, 5),
        },
        "image": f"media/products/sku-{seq:06d}.jpg",
    }


def gen_store(
    rng: random.Random, seq: int, *, manager_uuid: str | None
) -> tuple[dict[str, Any], str]:
    city, state = rng.choice(data.CITIES)
    street_no = rng.randint(10, 9999)
    street = f"{street_no} {rng.choice(data.STREET_NAMES)} {rng.choice(data.STREET_SUFFIXES)}"
    name = f"{city} {rng.choice(data.COMPANY_WORDS)} Store"
    payload: dict[str, Any] = {
        "name": name,
        "street": street,
        "city": city,
        "state": state,
        "zip": f"{rng.randint(10000, 99999)}",
        "opened": random_date(rng, 1990, 2025),
        "sq_ft": rng.randint(1200, 120_000),
        "hours": {
            day: "closed" if day in ("sat", "sun") and rng.random() < 0.2 else "09:00-18:00"
            for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        },
    }
    if manager_uuid is not None:
        payload["manager"] = {"type": "contact", "uuid": manager_uuid}
    return payload, f"{_slugish(name)}-{seq}"


def gen_order(
    rng: random.Random,
    seq: int,
    *,
    customer_uuid: str,
    product_uuids: list[str],
) -> dict[str, Any]:
    chosen = rng.sample(product_uuids, k=min(len(product_uuids), rng.randint(1, 5)))
    total = round(rng.uniform(9.99, 5000.0), 2)
    state = rng.choice(data.US_STATES)[0]
    status = rng.choices(data.ORDER_STATUSES, weights=data.ORDER_STATUS_WEIGHTS, k=1)[0]
    return {
        "order_no": f"ORD-{seq:07d}",
        "customer": {"type": "contact", "uuid": customer_uuid},
        "products": [{"type": "product", "uuid": uuid} for uuid in chosen],
        "total": total,
        "placed_at": random_datetime(rng, 2021, 2026),
        "order_status": status,
        "ship_state": state,
        "gift": rng.random() < 0.12,
    }
