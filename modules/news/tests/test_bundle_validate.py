"""An uploaded ``news/`` section is refused (422) for anything apply could not survive (#80)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bundle_app import article, bundle_host, download, rezip, take, upload
from news.integrations.bundle.validate import validate
from pagebuilder.contracts.bundle import ValidateContext


def _doc(slug: str = "launch", **fields) -> dict:
    return {
        "slug": slug,
        "locale": "en",
        "title": slug.title(),
        "status": "draft",
        "draft_data": {"content": []},
        "translation_group": f"g-{slug}",
        "tags": [],
        **fields,
    }


def _section(tmp_path: Path, files: dict[str, object]) -> ValidateContext:
    root = tmp_path / "news"
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
    return ValidateContext(dir=root, version=1, media_names=frozenset({"hero.png"}))


def _refusal(tmp_path: Path, files: dict[str, object]) -> str:
    ctx = _section(tmp_path, files)
    with pytest.raises(Exception) as caught:
        validate(ctx)
    assert type(caught.value).__name__ == "BundleError"
    return str(caught.value)


def test_a_well_formed_section_passes(tmp_path):
    validate(
        _section(
            tmp_path,
            {
                "articles/launch.json": _doc(og_image="asset://hero.png", tags=["Python"]),
                "articles/de__start.json": _doc("start", locale="DE", translation_group="g-launch"),
                "tags.json": [{"name": "Python", "slug": "python"}],
                "categories.json": [{"name": "Updates", "slug": "updates", "position": 0}],
                "redirects.json": [{"from_slug": "old", "locale": "en", "to_slug": "launch"}],
                "tag_redirects.json": [{"from_slug": "py", "to_slug": "python"}],
            },
        )
    )


def test_an_absent_section_directory_passes(tmp_path):
    validate(ValidateContext(dir=tmp_path / "news", version=1, media_names=frozenset()))


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"articles/a.json": _doc(status="archived")}, "invalid status"),
        ({"articles/a.json": _doc(status=["draft"])}, "invalid status"),
        ({"articles/a.json": _doc(status={"x": 1})}, "invalid status"),
        ({"articles/a.json": _doc(locale="not a locale!")}, "unreadable locale"),
        ({"articles/a.json": _doc(slug="../escape")}, "invalid slug"),
        ({"articles/a.json": _doc(slug="Has Space")}, "invalid slug"),
        ({"articles/a.json": _doc(title="x" * 301)}, "invalid title"),
        ({"articles/a.json": _doc(pinned="yes")}, "invalid pinned"),
        ({"articles/a.json": _doc(publish_at="tomorrow")}, "invalid publish_at"),
        ({"articles/a.json": {"slug": "a"}}, "missing locale, status, title"),
        ({"articles/a.json": ["not", "a", "document"]}, "not an article document"),
        ({"articles/a.json": "{not json"}, "not readable JSON"),
        ({"articles/a.json": _doc(og_image="asset://gone.png")}, "gone.png"),
        ({"articles/a.json": _doc(tags=["Unlisted"])}, "Unlisted"),
        (
            {
                "articles/a.json": _doc("same"),
                "articles/b.json": _doc("same", translation_group="x"),
            },
            "en/same twice",
        ),
        (
            {
                "articles/a.json": _doc("a", translation_group="g"),
                "articles/b.json": _doc("b", translation_group="g"),
            },
            "g/en twice",
        ),
        ({"categories.json": {"name": "x"}}, "categories.json is not a list"),
        (
            {"categories.json": [{"name": "A", "slug": "a", "position": 2**63}]},
            "malformed entry",
        ),
        ({"categories.json": [{"name": "  ", "slug": "a", "position": 0}]}, "malformed entry"),
        (
            {
                "categories.json": [
                    {"name": "Updates", "slug": "a", "position": 0},
                    {"name": "updates ", "slug": "b", "position": 1},
                ]
            },
            "which are the same name",
        ),
        (
            {"tags.json": [{"name": "Python", "slug": "a"}, {"name": "PYTHON", "slug": "b"}]},
            "which are the same name",
        ),
        ({"categories.json": [{"name": "A", "slug": "a", "position": "1"}]}, "malformed entry"),
        (
            {"tags.json": [{"name": "A", "slug": "a"}, {"name": "B", "slug": "a"}]},
            "tags.json lists a twice",
        ),
        (
            {"redirects.json": [{"from_slug": "x", "locale": "en", "to_slug": "y"}] * 2},
            "redirects.json lists en/x twice",
        ),
    ],
)
def test_a_malformed_section_is_refused(tmp_path, files, message):
    assert message in _refusal(tmp_path, files)


def test_a_symlinked_document_is_refused(tmp_path):
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps(_doc()))
    ctx = _section(tmp_path, {"tags.json": []})
    (ctx.dir / "articles").mkdir()
    (ctx.dir / "articles" / "a.json").symlink_to(outside)
    with pytest.raises(Exception, match="symlink"):
        validate(ctx)


@pytest.mark.asyncio
async def test_upload_refuses_a_malformed_news_section(tmp_path):
    async with bundle_host(tmp_path) as client:
        await article(client, "launch")
        snapshot = await take(client)
        data = await download(client, snapshot["id"])
        assert (await upload(client, data)).status_code == 201

        bad = rezip(data, {"news/articles/launch.json": _doc(status="archived")})
        refused = await upload(client, bad)

        assert refused.status_code == 422
        assert "news/articles/launch.json has an invalid status" in refused.json()["detail"]

        # Past an INTEGER column: refused here, not as a 500 at approval.
        huge = [{"name": "Updates", "slug": "updates", "position": 9223372036854775808}]
        refused = await upload(client, rezip(data, {"news/categories.json": huge}))
        assert refused.status_code == 422
        assert "news/categories.json has a malformed entry" in refused.json()["detail"]
