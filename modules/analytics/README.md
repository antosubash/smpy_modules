# SimpleModule Analytics

Native, tenant-scoped traffic and anonymous application events for SimpleModule
hosts. Includes a dashboard, daily visitor estimates, sessions, custom events,
referrers, campaign and device breakdowns, and optional local country/region/city
geolocation. Public and application tracking are separate opt-ins.

## Install

```sh
pip install 'simple_module_analytics[geoip]'
```

Install the package in your host and generate/apply that host's Alembic migration.
The base package also works without the GeoIP extra. For location reporting,
provision a GeoLite2 City MMDB file separately and configure its absolute path in
the database-backed Analytics settings. No IP lookup service is called.

## Usage

Open **Analytics**, create a property, enter the exact site origin and allowed
route patterns, and enable tracking. New properties start paused. Application
routes such as `/records/:id` store the pattern instead of the record identifier.
The demo host includes the Inertia adapter; other hosts can use the exported
`startHostAnalytics`, `initAnalytics`, and `track` frontend functions.

No cookies, persistent browser identifiers, raw IP addresses or device coordinates
are stored. Do Not Track and Global Privacy Control are honored. Location and
visitor identity are estimates. Reports are tenant-restricted and require
`analytics.view`; property changes require `analytics.manage`. Retention defaults
to 90 days. Long-range reports scan raw events, so benchmark your deployment
before relying on interactive performance at high traffic volumes.

See [the guide](docs/index.md) for setup, custom events, metrics, privacy,
geolocation provisioning, retention operations and verification.
