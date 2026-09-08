/**
 * A URL field for a picture, with the picture under it.
 *
 * Not a media picker, and it does not pretend to be one — see the README's
 * **Known gaps**. An image is still addressed by URL here, and it has to be:
 * the library belongs to pagebuilder and these blocks render on a host that
 * never installed it. This only removes the part of the extra step that was
 * pure guesswork, which is whether the address the writer just pasted is the
 * picture they meant, a 404, or a login page.
 *
 * The whole of it is an `<img>` and two pieces of state. Nothing is fetched,
 * nothing is validated against a list of hosts, and no dependency is added to
 * the bundle these blocks already ship in.
 *
 * Puck renders a `custom` field's `render` on its own — no label wrapper — so
 * this supplies `FieldLabel`, and `AutoField` for the input itself rather than
 * a hand-rolled `<input>`, which would drift from every other field in the
 * panel the first time Puck restyles one.
 */

import { AutoField, type CustomField, FieldLabel } from '@puckeditor/core';
import { useState } from 'react';

export type PreviewStatus = 'idle' | 'loaded' | 'failed';

/** What the field says when the address loads nothing.
 *
 * Phrased as an observation rather than an error: an address that is merely
 * unreachable from the writer's network, or not an image yet because nobody
 * has uploaded it, is not a mistake the editor should be scolding them for. */
const NOT_LOADED = 'Nothing loaded from that address.';

interface Seen {
  url: string;
  status: PreviewStatus;
}

/**
 * The status to show for `url`, given the last address this field saw.
 *
 * A new address is `idle` — not yet known to be anything — even when the one
 * before it failed. Hence the pair rather than a single `failed` boolean,
 * which is the shape this obviously wants and the bug it obviously has: a
 * writer who pastes a good URL over a typo keeps being told nothing loaded,
 * and the field reads as broken rather than as reporting.
 */
export function statusFor(seen: Seen, url: string): PreviewStatus {
  return seen.url === url ? seen.status : 'idle';
}

/** Whether there is a picture to try to draw. Nothing for an empty field —
 *  a placeholder box where no address has been typed is furniture. */
export function showsPreview(url: string, status: PreviewStatus): boolean {
  return url.trim() !== '' && status !== 'failed';
}

/** The line under the field, or nothing to say. */
export function previewNote(url: string, status: PreviewStatus): string | null {
  return url.trim() !== '' && status === 'failed' ? NOT_LOADED : null;
}

function ImageUrlPreview({ url }: { url: string }) {
  const [seen, setSeen] = useState<Seen>({ url, status: 'idle' });
  const status = statusFor(seen, url);
  const note = previewNote(url, status);

  return (
    <>
      {showsPreview(url, status) && (
        // `alt=""` on purpose: the picture is the field's own feedback, and the
        // alt text a reader gets is the block's, edited next door.
        <img
          src={url}
          alt=""
          className="mt-2 max-h-32 rounded border object-contain"
          onLoad={() => setSeen({ url, status: 'loaded' })}
          onError={() => setSeen({ url, status: 'failed' })}
        />
      )}
      {note && <p className="mt-2 text-xs text-muted-foreground">{note}</p>}
    </>
  );
}

/** A labelled URL field that shows what it points at. */
export function imageUrlField(label: string): CustomField<string> {
  return {
    type: 'custom',
    // `name` is deliberately not forwarded: `FieldProps` has none, and the
    // focus tracking that reads it lives on the wrapper Puck already put
    // around this render, not on the input inside it.
    render: ({ id, onChange, readOnly, value }) => (
      <FieldLabel label={label}>
        <AutoField
          field={{ type: 'text' }}
          id={id}
          value={value}
          onChange={onChange}
          readOnly={readOnly}
        />
        <ImageUrlPreview url={value ?? ''} />
      </FieldLabel>
    ),
  };
}
