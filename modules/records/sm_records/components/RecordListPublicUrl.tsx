import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useRef, useState } from 'react';

import { normalizePublicPrefix } from '../utils/public-api';

/**
 * A public type's read API URL, shown on the record list (U14/Missing-15).
 *
 * `TypeEditor`'s own `PublicField` already shows this once `is_public` is
 * turned on — its header comment says so — but that is the *only* place it
 * showed up, and the hub's own row-links-to-records design (UX-R13.1) means
 * an admin reaches the list, not the schema editor, on every ordinary visit.
 * "You cannot verify the thing you just turned on" without a detour through
 * "Edit schema" is exactly the gap Missing-15 names.
 *
 * A smaller cousin of `PublicField` rather than a shared import: this has no
 * switch to toggle and nothing to validate, only the URL and a copy button.
 */
export function RecordListPublicUrl({
  typeKey,
  publicRoutePrefix,
}: {
  typeKey: string;
  publicRoutePrefix?: string;
}) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const url = `${normalizePublicPrefix(publicRoutePrefix)}/${typeKey}`;

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the code line is still selectable.
    }
  };

  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      {t('records.records.public_url_label', { defaultValue: 'Public at' })}
      <code
        className="w-fit rounded-md border bg-muted px-2 py-0.5 text-xs"
        data-testid="records-list-public-url"
      >
        {url}
      </code>
      <Button type="button" variant="outline" size="xs" onClick={() => void copy()}>
        {copied
          ? t('records.type_editor.public_url_copied', { defaultValue: 'Copied' })
          : t('records.type_editor.public_url_copy', { defaultValue: 'Copy' })}
      </Button>
    </p>
  );
}
