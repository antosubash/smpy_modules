# Security policy

## Supported versions

Releases are lockstep: one version covers every `simple_module_*` package in
this repository. Security fixes go into the next release; only the latest
release is supported, so upgrade to it to get a fix. The demo host in `host/` is
a development app and is never published.

## Reporting a vulnerability

Please do **not** open a public issue, pull request or discussion for a
vulnerability.

Report it privately through GitHub instead: on the repository's **Security**
tab, choose **Report a vulnerability**. Include the affected module and
version, the steps to reproduce, and the impact you expect.

If that form is not available, open an issue that says only that you have a
security report and asks for a private contact, with no details of the problem.

The conversation then continues privately in that report. Once a fix is
released, the advisory is published, crediting the reporter unless you ask
otherwise.

## Scope

In scope: the modules under `modules/` and the scripts that ship with them.
Vulnerabilities in the SimpleModule framework itself (`simple_module_core`,
`simple_module_db`, `simple_module_hosting`, …) belong in the framework's own
repository.
