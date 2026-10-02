# Billing documentation

`simple_module_billing` sells plans to the organisations of a multi-tenant
SimpleModule app. An administrator defines **plans** (price, seats, features);
each organisation has at most one **subscription** that decides which plan is
in force; Stripe takes the money. A plan's limits are answered through the
`tenants` module's entitlement seam, so the rest of the app asks "may this
organisation do X?" without knowing billing exists.

Start with the document that matches what you are trying to do.

## Who should read what

| You are | Read |
|---|---|
| A platform administrator setting up plans, or an organisation owner paying for one | [user-guide.md](user-guide.md) |
| A developer calling the billing API, or gating a feature on a plan | [api-reference.md](api-reference.md) |
| An operator installing it, connecting Stripe, or answering "why is this organisation suspended?" | [operations.md](operations.md) |
| A developer changing the module or adding a payment provider | [architecture.md](architecture.md) |

### [user-guide.md](user-guide.md) — for administrators and owners

The three admin screens (Plans, Subscriptions, Stripe connection) and the
organisation's Billing page, using the exact UI labels: what each plan field
means, which combinations the editor refuses and why, what each subscription
status does to an organisation, and what an owner sees when a payment fails.

### [api-reference.md](api-reference.md) — for integrators

Every endpoint under `/api/billing` and `/api/billing/admin`, plus the Stripe
webhook: method, permission, request and response shapes, and the full error
table. Also how another module reads a plan's limits and features without
importing billing.

### [operations.md](operations.md) — for operators

Installing and migrating, every setting, connecting Stripe step by step
(including the one Stripe dashboard setting the dunning behaviour depends on),
running `smpy billing reconcile`, and a troubleshooting table that starts from
the symptom.

### [architecture.md](architecture.md) — for maintainers

The four tables, how a webhook becomes local state, the lifecycle rules as a
table, why plans resolve the way they do, the transaction rules every
out-of-request write must follow, and how to add a second payment provider.

## The module in one paragraph

Billing owns four tables keyed by `tenant_id` and changes nothing in `tenants`.
Plans live in the database, not in Stripe; Stripe price IDs are attached to
them. A subscription whose status is `trialing`, `active` or `past_due` grants
its plan; anything else falls back to the free default plan. Webhooks are never
trusted for state: each one re-fetches the subscription from Stripe and writes
what Stripe says now, so duplicate and out-of-order deliveries are harmless.
When a subscription turns `unpaid`, billing suspends the organisation through
`TenantService.set_status`; paying again reactivates it. An installation with
no Stripe account runs on the `manual` provider, where administrators assign
plans by hand and nobody is charged.
