"""Unit tests for the seam news borrows pagebuilder through.

``news.integrations`` is the only package here that imports pagebuilder, so it
is also the only place where a change on pagebuilder's side (or its absence)
can break news silently. This is asserted rather than left to review because it
is the kind of thing a single convenient import quietly undoes, and nothing
else would fail.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta, timezone

import news
from news import settings as news_settings
from news.display_date import as_display_date
from news.integrations import pagebuilder as pb
from news.settings import NewsSettings, public_article_path


def _imports_pagebuilder(node: ast.AST) -> bool:
    """Whether one AST node is an import of pagebuilder.

    Parsed rather than grepped. The regex this replaced matched any line
    *beginning* "from pagebuilder", which a wrapped docstring does about as
    often as an import does — ``endpoints/views.py`` tripped it with the prose
    "borrowed \\n from pagebuilder where that module is installed". Parsing also
    catches the opposite mistake, an import the regex cannot see: one indented
    inside a function still binds the package.
    """
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and node.level == 0:
        names = [node.module or ""]
    else:
        return False
    return any(name == "pagebuilder" or name.startswith("pagebuilder.") for name in names)


class TestNoOtherModuleImportsPagebuilder:
    def test_the_seam_is_the_only_importer(self) -> None:
        """The rule the whole package exists to state.

        The unit is ``news/integrations/`` rather than one file in it — which
        is what the package docstring has always said. It outgrew a single
        module when the 300-line cap split the content locales into a sibling;
        both still sit behind the same boundary, and widening the check to the
        directory is what keeps it checkable by reading one directory listing.

        Every node, not just module scope: outside the seam a deferred import
        is no better than an eager one, because the package is bound either
        way the moment that code path runs.
        """
        root = pathlib.Path(news.__file__).parent
        seam = root / "integrations"
        offenders = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if seam not in path.parents
            and any(_imports_pagebuilder(n) for n in ast.walk(ast.parse(path.read_text())))
        )

        assert offenders == []

    def test_the_seam_itself_defers_its_imports(self) -> None:
        """Being inside the seam is not enough — the import must be deferred.

        ``news.settings`` reads the content locales, which live in
        ``integrations.locales``. If that module imported pagebuilder at module
        scope, importing ``news.settings`` would pull pagebuilder in, and news
        would stop booting on a host that installed it without the optional
        ``pagebuilder`` extra — the arrangement this module's whole shape
        exists to allow. The check above would not catch it, because the
        offending import sits legitimately inside the seam.
        """
        seam = pathlib.Path(news.__file__).parent / "integrations"
        offenders = sorted(
            path.name
            for path in seam.glob("*.py")
            # Module scope only, deliberately: inside the seam a deferred
            # import is the whole point, and only a top-level one makes the
            # package a hard requirement of importing news.
            if any(_imports_pagebuilder(n) for n in ast.parse(path.read_text()).body)
        )

        assert offenders == [], (
            f"{offenders} import pagebuilder at module scope; defer it into the "
            "function that needs it so news imports without the optional extra"
        )


class TestNewsImportsWithoutPagebuilder:
    """The property the two tests above are only a proxy for.

    They check *where* imports sit; this checks what that buys — that news
    boots on a host which never installed the optional extra. Worth asserting
    directly, because the proxy can pass while the property fails: an import
    deferred into a function still raises when the function runs, and a
    ``from pagebuilder import x`` written as ``importlib.import_module`` is
    invisible to a parser.

    In a subprocess, because the only honest way to ask is to make the package
    genuinely unimportable, and this workspace has it installed.
    """

    def test_the_whole_module_imports_with_the_package_blocked(self) -> None:
        import subprocess
        import sys
        import textwrap

        probe = textwrap.dedent("""
            import sys

            class Blocker:
                def find_spec(self, name, path=None, target=None):
                    if name == "pagebuilder" or name.startswith("pagebuilder."):
                        raise ImportError("pagebuilder is not installed")
                    return None

            sys.meta_path.insert(0, Blocker())

            # Everything a host touches on the way up. `settings` and `models`
            # are the load-bearing two: `models` is what alembic imports, so a
            # hard dependency here stops the database migrating at all.
            import news.settings
            import news.models
            import news.module
            import news.locales
            import news.service
            import news.endpoints.api
            import news.endpoints.views

            from news.integrations import pagebuilder as pb

            assert pb.available() is False, "available() must answer, not raise"
            assert pb.page_editor_path(7) == ""
            assert news.locales.supported() == ("en",)
            assert news.locales.default() == "en"

            print("ok")
        """)

        done = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True
        )

        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().endswith("ok")


class TestAvailability:
    """The seam's whole job on a host that did not install the extra.

    There was a ``TestArticleStatus`` here that walked ``pb.PageStatus`` and
    checked news could name every one of them. It went with the re-export: an
    article's status is a column on ``NewsArticle`` now, and news' enum answers
    to nothing in another module. Keeping the test would have pinned a coupling
    this branch exists to remove.
    """

    def test_availability_is_a_question_and_not_an_import(self) -> None:
        # Truthy or falsy either way — what matters is that asking is safe.
        assert pb.available() in (True, False)

    def test_the_links_go_nowhere_without_it(self, monkeypatch) -> None:
        """A missing neighbour is a missing affordance, not a broken link.

        The frontend renders a section's "see all" only when it has somewhere
        to send you, so "" is what a host without pagebuilder should get.
        """
        monkeypatch.setattr(pb, "available", lambda: False)

        assert pb.page_editor_path(7) == ""
        assert pb.media_library_path() == ""
        assert pb.page_search_path("sensors") == ""


class TestRoutes:
    def test_the_editor_path_names_the_page(self) -> None:
        assert pb.page_editor_path(7) == "/pagebuilder/7/edit"

    def test_the_media_path_is_a_pagebuilder_route(self) -> None:
        assert pb.media_library_path().startswith("/pagebuilder")

    def test_the_page_search_path_carries_the_query(self) -> None:
        assert "sensors" in pb.page_search_path("sensors")


class TestDisplayDate:
    """``published_at`` is a date; the API accepts an instant."""

    def test_a_naive_datetime_is_taken_at_face_value(self) -> None:
        normalised = as_display_date(datetime(2026, 2, 1, 22, 30))

        assert normalised == datetime(2026, 2, 1, tzinfo=UTC)

    def test_an_offset_is_not_applied_before_truncating(self) -> None:
        """The bug this exists to remove.

        6pm on the 1st in UTC-6 is the 2nd in UTC. Converting first and
        truncating second stored and listed it as the 2nd — a day the author
        never picked.
        """
        evening = datetime(2026, 2, 1, 18, 0, tzinfo=timezone(timedelta(hours=-6)))

        assert as_display_date(evening) == datetime(2026, 2, 1, tzinfo=UTC)

    def test_a_time_already_at_midnight_utc_is_unchanged(self) -> None:
        midnight = datetime(2026, 2, 1, tzinfo=UTC)

        assert as_display_date(midnight) == midnight

    def test_undated_stays_undated(self) -> None:
        # An undated article is work in progress — a real value, not a missing
        # one, so it must not be turned into a date.
        assert as_display_date(None) is None


class TestPublicArticlePath:
    """Where an article serves. Its own prefix, not pagebuilder's generic one —
    an article used to sit at ``/p/{slug}`` next to the contact page, so the
    address said nothing about what the document was."""

    def test_the_default_prefix_is_the_modules_own(self) -> None:
        assert public_article_path("estonia") == "/news/estonia"

    def test_a_deployment_can_move_it(self) -> None:
        """A setting rather than a constant because it is the one thing here a
        site owner has an opinion about — /news, /blog, or a word in their own
        language."""
        news_settings.use(NewsSettings(public_route_prefix="/aktuelles"))

        assert public_article_path("estonia") == "/aktuelles/estonia"

    def test_a_trailing_slash_does_not_double(self) -> None:
        news_settings.use(NewsSettings(public_route_prefix="/blog/"))

        assert public_article_path("estonia") == "/blog/estonia"
