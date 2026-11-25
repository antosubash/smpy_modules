"""Coded stale-draft refusals, distinct from slug and workflow conflicts."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class PageConflict(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=409, detail="This page was changed elsewhere")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PageConflict)
    async def page_conflict(_request: Request, exc: PageConflict) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": "page_conflict"},
        )
