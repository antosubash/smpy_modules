# Code layout

`sm_ai` follows the repo's [module layout](../../../docs/module-layout.md).

| Path | Responsibility |
| --- | --- |
| `module.py` | The `simple_module` entry point; stays at the package root |
| `contracts/` | The stable Python surface other modules consume, including schemas and errors |
| `locales/`, `pages/` | Catalogues and Inertia pages discovered by the host |
| `core/` | Constants, encryption, DB-backed settings, worker hydration, shared service state and the base-URL address rules (`url_safety.py`, a copy of images' guard) |
| `connections/` | Provider model resolution and model discovery, and the base-URL guard: `base_url.py` (save and build checks) and `pinned.py` (the address-pinned HTTP client), `clients.py` (one shared client per event loop and origin) |
| `metering/requests.py` | Optional billing integration for HTTP and worker AI requests |
| `web/` | Settings service, request dependencies, CSRF, endpoints and the probe failure classes (`probe_errors.py`) |
| `ui/` | Components and frontend utilities, with their unit tests beside them |

Area initializers contain only docstrings. Import an implementation module
rather than running sibling initialization through an area import.

Python tests mirror these areas under `tests/`; `tests/core/` also holds boot,
contract and discovery checks. Shared stubs and worker helpers live in
`tests/support/`. The module has no tables, migrations or Celery tasks of its
own: consumers call `sm_ai.contracts` from their workers.
