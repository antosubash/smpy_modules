import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { type PreviewInput, usePreview } from '../../hooks/usePreview';
import { keys, useT } from '../../utils/i18n';

const copy = keys.newsletter.preview;

const WARNINGS: Record<string, string> = {
  relative_urls: copy.warning.relative_urls,
  physical_address_missing: copy.warning.physical_address_missing,
  empty_body: copy.warning.empty_body,
};

type Tab = 'html' | 'text';
type Width = 600 | 375;

/** The email as it will be sent: HTML in a sandboxed frame, or plain text.
 *
 *  The frame has no `sandbox` tokens at all — no scripts, no same-origin — so
 *  whatever the rendered HTML holds cannot reach this page (R4).
 */
export function PreviewPane(props: Omit<PreviewInput, 'enabled'> & { enabled?: boolean }) {
  const { t } = useT();
  const { preview, error, loading } = usePreview({ ...props, enabled: props.enabled ?? true });
  const [tab, setTab] = useState<Tab>('html');
  const [width, setWidth] = useState<Width>(600);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
      <div className="flex flex-wrap items-center gap-2">
        {(['html', 'text'] as const).map((id) => (
          <Button
            key={id}
            type="button"
            size="sm"
            variant={tab === id ? 'default' : 'outline'}
            aria-pressed={tab === id}
            onClick={() => setTab(id)}
          >
            {t(id === 'html' ? copy.tab_html : copy.tab_text)}
          </Button>
        ))}
        {tab === 'html' &&
          ([600, 375] as const).map((w) => (
            <Button
              key={w}
              type="button"
              size="sm"
              variant={width === w ? 'secondary' : 'ghost'}
              aria-pressed={width === w}
              onClick={() => setWidth(w)}
            >
              {t(w === 600 ? copy.desktop : copy.mobile)}
            </Button>
          ))}
        {loading && (
          <span role="status" className="text-xs text-muted-foreground">
            {t(copy.loading)}
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {preview && (
        <>
          <p className="text-sm">
            <span className="text-muted-foreground">{t(copy.subject)} </span>
            {preview.subject}
          </p>
          {preview.warnings.length > 0 && (
            <ul className="space-y-1 rounded-md border bg-amber-50 p-3 text-sm text-amber-900">
              {preview.warnings.map((code) => (
                <li key={code}>{Object.hasOwn(WARNINGS, code) ? t(WARNINGS[code]) : code}</li>
              ))}
            </ul>
          )}
          {tab === 'html' ? (
            <iframe
              sandbox=""
              srcDoc={preview.html}
              title={t(copy.frame_title)}
              style={{ width, maxWidth: '100%' }}
              className="mx-auto min-h-[480px] flex-1 border bg-white"
            />
          ) : (
            <pre className="whitespace-pre-wrap rounded-md border bg-muted p-3 text-sm">
              {preview.text}
            </pre>
          )}
        </>
      )}
    </div>
  );
}
