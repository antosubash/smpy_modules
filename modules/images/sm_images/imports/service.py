"""Starting a GeoJSON import from a request: :func:`start_import`.

Everything the client can get wrong is refused **before** a job exists, with a
422 and a code: the kind, the mapping, the source (exactly one of an uploaded
file or a URL), an unsafe source URL (the SSRF guard resolves it now - and
``safe_stream`` checks it again when the runner fetches, against DNS
rebinding), and for an upload a document that is not a complete
FeatureCollection or holds more than ``geojson_max_features``.

Then the source is staged (an upload) or left for the runner (a URL), the job
row commits, and the runner is launched. If a broker refuses the message, the
job is failed and its staging deleted (503) rather than left for reconcile to
discover as an orphan.
"""

from __future__ import annotations

import logging
import uuid
from typing import IO

import httpx
from pydantic import ValidationError

from sm_images.errors import FileTooLarge, Invalid, ServiceUnavailable
from sm_images.imports import jobs, launch, staging, terminal
from sm_images.imports.dns import resolve_bounded
from sm_images.imports.errors import FetchError
from sm_images.imports.geojson_stream import GeoJSONError
from sm_images.imports.lookup import get
from sm_images.imports.mapping import Mapping, MappingError
from sm_images.imports.url_safety import DEFAULT_ALLOWED_PORTS, UnsafeURLError, check_url
from sm_images.models import Collection, ImportJob
from sm_images.models.enums import ImportKind
from sm_images.pipeline.runtime import Runtime

__all__ = ["invalid", "start_import"]

logger = logging.getLogger(__name__)


def invalid(code: str, detail: str) -> Invalid:
    return Invalid(detail, code=code)


def _mapping(kind: str, raw: str) -> tuple[ImportKind, Mapping]:
    try:
        parsed_kind = ImportKind(kind)
    except ValueError as exc:
        raise invalid("invalid_import_kind", "Unknown import kind") from exc
    try:
        mapping = Mapping.model_validate_json(raw or "{}")
    except ValidationError as exc:
        raise invalid("invalid_mapping", "The property mapping is not valid") from exc
    try:
        return parsed_kind, mapping.require(parsed_kind)
    except MappingError as exc:
        raise invalid(exc.code, "The property mapping cannot drive this import") from exc


async def _check_source_url(url: str) -> str:
    url = url.strip()
    try:
        check_url(url)
        await resolve_bounded(httpx.URL(url), DEFAULT_ALLOWED_PORTS)
    except UnsafeURLError as exc:
        raise invalid("unsafe_source_url", "The source URL is not allowed") from exc
    except FetchError as exc:
        raise invalid("unsafe_source_url", "The source URL could not be resolved") from exc
    return url


async def start_import(
    runtime: Runtime,
    tenant: str,
    collection: Collection,
    *,
    kind: str,
    mapping: str,
    source_url: str | None,
    upload: IO[bytes] | None,
    auto_run_prompts: bool = True,
    created_by: str | None = None,
    access_basis: str | None = None,
) -> ImportJob:
    parsed_kind, parsed = _mapping(kind, mapping)
    if (upload is None) == (not source_url):
        raise invalid("source_required", "Send exactly one of a GeoJSON file or a source URL")
    settings = runtime.settings()
    job_id = uuid.uuid4()
    common = {"kind": parsed_kind, "mapping": parsed, "job_id": job_id}
    if upload is not None:
        if staging.size(upload) > settings.geojson_max_bytes:
            raise FileTooLarge("The GeoJSON file is too large")
        try:
            staged = await staging.put_upload(
                runtime, tenant, job_id, upload, settings.geojson_max_features
            )
        except GeoJSONError as exc:
            raise invalid(exc.code, "The GeoJSON file cannot be imported") from exc
        row = await jobs.create_job(
            runtime,
            tenant,
            collection.id,
            staged=staged,
            auto_run_prompts=auto_run_prompts,
            created_by=created_by,
            access_basis=access_basis,
            **common,
        )
    else:
        assert source_url is not None
        url = await _check_source_url(source_url)
        row = await jobs.create_job(
            runtime,
            tenant,
            collection.id,
            source_url=url,
            auto_run_prompts=auto_run_prompts,
            created_by=created_by,
            access_basis=access_basis,
            **common,
        )
    try:
        await launch.launch_runner(runtime, tenant, row.id, row.generation)
    except Exception as exc:
        if runtime.is_eager():  # the work itself failed: reconcile retries it
            logger.exception("images.import.eager_run_failed job=%s", row.id)
        else:
            await terminal.fail(runtime, tenant, row.id, row.generation, "dispatch_failed")
            raise ServiceUnavailable("The import could not be queued") from exc
    return await get(runtime, tenant, row.id)
