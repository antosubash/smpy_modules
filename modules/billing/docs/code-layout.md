# Code layout

`sm_billing` follows the repo's [module layout](../../../docs/module-layout.md).

| Path | Responsibility |
| --- | --- |
| `module.py` | The framework's `simple_module` entry point |
| `cli.py` | The `simple_module_cli.cli_plugins` entry point for `smpy billing` |
| `models/` | SQLModel tables, discovered as `sm_billing.models` by the database module |
| `contracts/` | Public subject, provider and metering interfaces |
| `locales/`, `pages/` | Catalogues and Inertia pages discovered by the host |
| `core/` | Constants, encryption, settings, shared state, startup and subject context |
| `web/` | Endpoints, request dependencies, schemas and HTTP services |
| `plans/` | Plan CRUD, effective-plan resolution and entitlements |
| `subscriptions/` | Lifecycle, provider sync, webhooks, seats and reconciliation |
| `subscriptions/deletion/` | Tenant/user teardown, claims and retry sweeps |
| `metering/` | Usage counters, gauge holds, quotas, reporting and retention |
| `providers/` | Provider factory, manual provider and Stripe integration |
| `ui/` | Components, hooks and frontend utilities, with adjacent unit tests |

Area initializers contain only docstrings. Python tests mirror the areas;
`tests/core/` includes boot, models, contracts and discovery checks. Shared
fixtures remain in `tests/conftest.py`, with helpers in `tests/support/`.
Billing owns no Celery tasks: its reconcile and metering loops run through
module startup, and workers consume the public contracts.
