"""The email body: a list of Puck ``content`` items, one discriminated union."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from sm_newsletter.content.merge import check_merge
from sm_newsletter.content.richtext import clean
from sm_newsletter.content.urls import check_image, check_link
from sm_newsletter.core.errors import InvalidBody
from sm_newsletter.core.headers import check_header_text

BLOCK_TYPES = (
    "Heading",
    "RichText",
    "Image",
    "Button",
    "Divider",
    "Spacer",
    "ArticleCard",
    "PageCard",
)
MAX_BLOCKS = 200

_TAGS = re.compile(r"<[^>]*>")


def _merge(value: str) -> str:
    check_merge(value)
    return value


def _rich(value: str) -> str:
    """Clean first (entities decode to the text a reader sees), then check the merge fields."""
    cleaned = clean(value)
    check_merge(cleaned)  # a tag inside a field leaves its braces behind
    check_merge(_TAGS.sub("", cleaned))  # and a field split across tags still counts as text
    return cleaned


def _heading_text(value: str) -> str:
    check_header_text(value, field="text")
    return _merge(value)


Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Link = Annotated[str, AfterValidator(check_link)]
ImageUrl = Annotated[str, AfterValidator(check_image)]
Merged = AfterValidator(_merge)


class _Props(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Id


class HeadingProps(_Props):
    text: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_heading_text)]
    level: Literal["1", "2"] = "2"
    align: Literal["left", "center"] = "left"


class RichTextProps(_Props):
    html: Annotated[str, Field(max_length=20000), AfterValidator(_rich)]


class ImageProps(_Props):
    src: Annotated[str, Field(min_length=1), AfterValidator(check_image)]
    alt: Annotated[str, Field(max_length=300), Merged] = ""
    href: Link | None = None
    width: Annotated[int, Field(ge=1, le=600)] = 600


class ButtonProps(_Props):
    label: Annotated[str, Field(min_length=1, max_length=80), Merged]
    href: Link
    align: Literal["left", "center", "right"] = "center"


class DividerProps(_Props):
    pass


class SpacerProps(_Props):
    size: Literal["sm", "md", "lg"] = "md"


class CardProps(_Props):
    source_id: Annotated[int, Field(gt=0)]
    title: Annotated[str, Field(max_length=300)] = ""
    excerpt: Annotated[str, Field(max_length=1000)] = ""
    image_url: ImageUrl = ""
    url: Link
    locale: Annotated[str, Field(max_length=16)] = ""
    snapshot_at: AwareDatetime


class _Block(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeadingBlock(_Block):
    type: Literal["Heading"]
    props: HeadingProps


class RichTextBlock(_Block):
    type: Literal["RichText"]
    props: RichTextProps


class ImageBlock(_Block):
    type: Literal["Image"]
    props: ImageProps


class ButtonBlock(_Block):
    type: Literal["Button"]
    props: ButtonProps


class DividerBlock(_Block):
    type: Literal["Divider"]
    props: DividerProps


class SpacerBlock(_Block):
    type: Literal["Spacer"]
    props: SpacerProps


class ArticleCardBlock(_Block):
    type: Literal["ArticleCard"]
    props: CardProps


class PageCardBlock(_Block):
    type: Literal["PageCard"]
    props: CardProps


Block = Annotated[
    HeadingBlock
    | RichTextBlock
    | ImageBlock
    | ButtonBlock
    | DividerBlock
    | SpacerBlock
    | ArticleCardBlock
    | PageCardBlock,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[list[Block]] = TypeAdapter(list[Block])
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")


def _path(loc: tuple[Any, ...]) -> str:
    out = "body"
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif part in BLOCK_TYPES:  # the union tag pydantic inserts
            continue
        else:
            out += "." + (part if _SAFE_KEY.match(part) else "?")
    return out


def _reason(err: Any) -> str:
    # The error type only: pydantic's message and input can quote the value.
    return "invalid value" if err["type"] == "value_error" else err["type"]


def parse_body(raw: object) -> list[Block]:
    """Validate a stored or submitted body. Raises InvalidBody naming the path, never the input."""
    if not isinstance(raw, list):
        raise InvalidBody("body: must be a list", code="invalid_body")
    if len(raw) > MAX_BLOCKS:
        raise InvalidBody(f"body: at most {MAX_BLOCKS} blocks", code="invalid_body")
    try:
        blocks = _ADAPTER.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        raise InvalidBody(f"{_path(first['loc'])}: {_reason(first)}") from None
    seen: set[str] = set()
    for i, block in enumerate(blocks):
        if block.props.id in seen:
            raise InvalidBody(f"body[{i}].props.id: duplicate")
        seen.add(block.props.id)
    return blocks


def dump_body(blocks: list[Block]) -> list[dict[str, Any]]:
    return [b.model_dump(mode="json") for b in blocks]
