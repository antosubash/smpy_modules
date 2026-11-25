"""Coded article refusals, preserving the API's readable detail."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

STALE_DETAIL = (
    "This article was changed somewhere else. Reload to get the latest version, "
    "then make your change again."
)


class ArticleConflict(HTTPException):
    """A stale base, distinct from slug collisions and invalid transitions."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=STALE_DETAIL)


class ArticleNotFound(HTTPException):
    """The article is trashed, purged or was never there: not a missing revision."""

    def __init__(self, detail: str = "Article not found.") -> None:
        super().__init__(status_code=404, detail=detail)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ArticleConflict)
    async def article_conflict(_request: Request, exc: ArticleConflict) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": "article_conflict"},
        )

    @app.exception_handler(ArticleNotFound)
    async def article_not_found(_request: Request, exc: ArticleNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": "article_not_found"},
        )
