import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { useEffect, useRef, useState } from 'react';

const ID = 'type-editor-is-public';

/**
 * The "Public" toggle and, once it is on, the URL the anonymous read API will
 * answer at (design §10).
 *
 * The URL is shown rather than merely described because `public_route_prefix`
 * is a database-backed setting: the browser has no other way to know where the
 * type it is about to expose will actually appear. Copying it is a button for
 * the same reason — the value is the one thing on this screen a reader needs
 * verbatim somewhere else.
 *
 * Split out of `TypeMetadataForm` for the 300-line cap, along the seam the
 * clipboard state already drew: this is the only part of that form with
 * behaviour of its own.
 */
export function PublicField({
  isPublic,
  typeKey,
  publicRoutePrefix,
  onChange,
}: {
  isPublic: boolean;
  /** The type's key — the last segment of the public URL. */
  typeKey: string;
  publicRoutePrefix: string;
  onChange: (isPublic: boolean) => void;
}) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  const none = t('records.type_editor.pointer_none', { defaultValue: 'None' });
  const publicUrl = `${publicRoutePrefix}/${typeKey || none}`;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The only timer in this module with no cleanup (L10) — a copy followed by
  // an unmount (navigating away, or toggling "Public" off) would otherwise
  // set state on a gone component.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(publicUrl);
      setCopied(true);
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the code line is still selectable.
    }
  };

  return (
    <>
      <div className="flex items-center gap-2 sm:col-span-2">
        <Switch
          id={ID}
          checked={isPublic}
          onCheckedChange={(checked) => onChange(checked === true)}
        />
        <Label htmlFor={ID} className="font-normal">
          {t('records.type_editor.is_public', { defaultValue: 'Public' })}
        </Label>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground sm:col-span-2">
        {t('records.type_editor.is_public_help', {
          defaultValue: "Exposes a read-only public API for this type's published records.",
        })}
      </p>

      {isPublic && (
        <div className="-mt-2 grid gap-1.5 sm:col-span-2" data-testid="records-public-url">
          <div className="flex flex-wrap items-center gap-2">
            <code className="w-fit rounded-md border bg-muted px-2 py-1 text-sm">{publicUrl}</code>
            <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
              {copied
                ? t('records.type_editor.public_url_copied', { defaultValue: 'Copied' })
                : t('records.type_editor.public_url_copy', { defaultValue: 'Copy' })}
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            {t('records.type_editor.is_public_url_help', {
              defaultValue:
                'Published records only, filterable only on indexed fields, and never expanded.',
            })}
          </p>
        </div>
      )}
    </>
  );
}
