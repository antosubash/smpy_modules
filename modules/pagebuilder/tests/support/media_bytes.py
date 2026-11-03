"""Restoring media, where a bundle's filenames are not its keys.

Split out of ``test_snapshot_apply`` only to stay under the file-size cap; the
subject is the same ``apply_bundle``.
"""

from __future__ import annotations

# A 1x1 PNG. Real bytes matter: MediaService sniffs content and rejects
# anything that is not actually an allowed image.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

# A second, larger PNG. Different bytes on purpose: the point of the test
# below is two assets that share a name but not a digest.
PNG_RED_2X2 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a"
    "730000001649444154789c63fccfc0c0c0c0c0c4c0c0c0c0c000000d1d01036a"
    "c29be90000000049454e44ae426082"
)
