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


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ArticleConflict)
    async def article_conflict(_request: Request, exc: ArticleConflict) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": "article_conflict"},
        )
