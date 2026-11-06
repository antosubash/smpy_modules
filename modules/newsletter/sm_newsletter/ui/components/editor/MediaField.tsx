/**
 * The image block's address: a URL input, plus *Choose from media* over
 * pagebuilder's library when pagebuilder is available (ruling R3).
 *
 * No upload: a file in file storage is permission-gated, so it would be broken
 * in every inbox. The picker lists pagebuilder's raster images through
 * `GET /api/newsletter/media` (the server keeps SVG out) and writes the chosen
 * one's URL into the same field the writer can type in.
 *
 * Puck renders a `custom` field without a label wrapper, so this supplies its
 * own `FieldLabel`; and it calls `render` as a plain function, so the hooks
 * live one level down, in `MediaInput`.
 */

import { AutoField, type CustomField, FieldLabel } from '@puckeditor/core';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useEffect, useState } from 'react';

import { SEARCH_DEBOUNCE_MS } from '../../hooks/useCampaignList';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { MediaHit } from '../../utils/types';

/** As the campaign list's search box: one request per word, not per keystroke. */

const copy = keys.newsletter.editor.media;

function MediaSearch({ onPick }: { onPick: (hit: MediaHit) => void }) {
  const { t } = useT();
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<MediaHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setHits(null);
      api
        .searchMedia(q, controller.signal)
        .then((found) => {
          setError(null);
          setHits(found);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(errorMessage(e, t));
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q, t]);

  return (
    <div className="mt-2 space-y-2 rounded border p-2">
      <Input
        type="search"
        aria-label={t(copy.search)}
        placeholder={t(copy.search)}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hits === null ? (
        <p className="text-xs text-muted-foreground">{t(copy.searching)}</p>
      ) : hits.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t(copy.no_results)}</p>
      ) : (
        <ul className="grid max-h-64 grid-cols-3 gap-2 overflow-y-auto">
          {hits.map((hit) => (
            <li key={hit.id}>
              <button
                type="button"
                className="block w-full rounded border hover:ring-2 hover:ring-primary"
                title={hit.filename}
                onClick={() => onPick(hit)}
              >
                <img src={hit.url} alt={hit.filename} className="h-16 w-full object-cover" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface MediaInputProps {
  labelKey: string;
  canPick: boolean;
  id: string;
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

function MediaInput({ labelKey, canPick, id, value, onChange, readOnly }: MediaInputProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <FieldLabel label={t(labelKey)}>
      <AutoField
        field={{ type: 'text' }}
        id={id}
        value={value}
        onChange={onChange}
        readOnly={readOnly}
      />
      {canPick && !readOnly && (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? t(copy.close) : t(copy.choose)}
          </Button>
          {open && (
            <MediaSearch
              onPick={(hit) => {
                onChange(hit.url);
                setOpen(false);
              }}
            />
          )}
        </>
      )}
    </FieldLabel>
  );
}

/** The image `src` field; `canPick` is `capabilities.pagebuilder`. */
export function mediaField(labelKey: string, canPick: boolean): CustomField<string> {
  return {
    type: 'custom',
    render: ({ id, value, onChange, readOnly }) => (
      <MediaInput
        labelKey={labelKey}
        canPick={canPick}
        id={id}
        value={value ?? ''}
        onChange={onChange}
        readOnly={readOnly}
      />
    ),
  };
}
