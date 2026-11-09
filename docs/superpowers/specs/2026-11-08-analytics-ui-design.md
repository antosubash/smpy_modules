# Analytics dashboard redesign

Approved in conversation on 2026-11-08. The approval covers implementation and updating PR #323. The subsequent instruction also requires an audit of every analytics query and its supporting indexes.

## Intent

Use Umami's compact reporting hierarchy inside the existing host shell: a small property/date/filter toolbar, four metrics, one large blue traffic chart, and two-column grouped rankings. Keep anonymous tracking, tenant isolation, UTC semantics, opt-in and all existing administration behavior.

## Presentation and interactions

- Reuse host typography, semantic surfaces, borders and light/dark themes. Use a module-local blue data accent, tabular numbers and restrained spacing.
- Toolbar: property picker, tracking status, active visitors, refresh, date range, Filters and secondary management. Today, last 7/30/90 days and custom dates are inclusive UTC ranges; custom dates apply explicitly.
- Filter fields open in a compact panel. Editing drafts causes no requests before Apply. Applied path/event/country/region/city conditions remain visible as removable chips. Country changes/removal clear region and city; region changes/removal clear city. Preserve All versus Unknown semantics.
- Metrics: pageviews, estimated visitors, estimated sessions and custom events. The larger labeled chart switches locally between daily pageviews and events. Preserve an accessible data table. Do not fabricate daily visitor/session trends, period comparisons or new metrics.
- Desktop rankings: Pages and Sources; Audience and Locations; Events/property breakdowns and Recent activity. Sources groups referrers and campaign dimensions; Audience groups browser/OS/device; Locations groups country/region/city. Tabs use already loaded data. Rows filter only supported server dimensions. Relative bars use the largest returned row, not a claimed percentage of all visitors. Show more reveals returned rows only.
- Property create/edit/setup and delete confirmation remain available behind secondary management controls. Preserve view/manage permission gates. Empty/error/loading and GeoIP-unavailable states remain actionable and accessible.
- Mobile: wrapping controls, a two-by-two metric strip, stacked ranking panels and no page-level horizontal overflow. Keyboard navigation, focus restoration and dark theme must work.
- Geography uses ranked tables and hierarchy filters. No world geometry, external map requests or additional map library is introduced.

## Query indexing

Inventory every property, collection, report, recent-activity, retention and deletion statement. Compare predicates/order/joins against indexes and inspect representative SQLite/Postgres plans. Add only useful composite/covering indexes, with matching SQLModel metadata and a new host-only migration. Verify upgrade/downgrade, one head and schema parity. Record legitimate sequential scans for broad aggregates instead of forcing indexes or claiming that all scans are defects. Remeasure write cost and report latency; a schema change must not silently regress ingestion.

## Populated evidence and verification

Use isolated synthetic data, never production: varied traffic over 90 UTC dates, public and application properties, meaningful paths, referrers/campaigns, devices/browsers/OS, approved events/property values, multiple readable country/region/city combinations and recent activity. Keep this visual fixture distinct from the regular capacity workload. Final screenshots follow verification/performance checks and use real production-bundle responses: overview, geography, event properties, normalized app routes, mobile and dark theme.

Run meaningful component tests, full frontend unit suite, typechecks/lint/rules/build, analytics backend/index/migration checks and production-bundle analytics E2E. Review independently. Reuse the established 9M-event benchmark databases for before/after index plans and measurements; report sample sizes and service/HTTP limits honestly. Update the existing PR with QA and performance results. Image upload still requires browser authentication/authorization if unavailable; approval of the UI design alone does not authorize a private Chrome profile.
