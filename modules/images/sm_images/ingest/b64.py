"""The one base64 decoder: the base64 upload route and base64 GeoJSON imports.

Raw base64 or a data URI; whitespace (MIME line breaks) is ignored. The size
is refused on the *encoded* length, before a byte is decoded, and again on the
decoded one. Failures are coded ``ImagesError``s: ``invalid_base64`` (422) and
``file_too_large`` (413).
"""

from __future__ import annotations

import base64
import binascii
from typing import Final

from sm_images.core import constants
from sm_images.core.errors import FileTooLarge, InvalidUpload

__all__ = ["decode_base64"]

_DATA_URI: Final = "data:"
_BAD: Final = "The image data is not valid base64"
_TOO_LARGE: Final = "The file is larger than the image size limit"


def decode_base64(text: str, max_bytes: int) -> bytes:
    text = text.strip()
    if text.startswith(_DATA_URI):
        text = text.partition(",")[2]
    text = "".join(text.split())
    if len(text) * 3 // 4 > max_bytes + 3:
        raise FileTooLarge(_TOO_LARGE)
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidUpload(_BAD, constants.CODE_INVALID_BASE64) from exc
    if not data:
        raise InvalidUpload(_BAD, constants.CODE_INVALID_BASE64)
    if len(data) > max_bytes:
        raise FileTooLarge(_TOO_LARGE)
    return data
