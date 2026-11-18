import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useState } from 'react';
import { keys, useT } from '../utils/i18n';

/** The feed's `https` address, a `webcal:` link that opens the calendar app, and a copy button.
 *  The origin is the page's own, read after mount (the server renders the path). */
export function SubscribeBox({ feedUrl }: { feedUrl: string }) {
  const { t } = useT();
  const copy = keys.events.public.subscribe;
  const [origin, setOrigin] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => setOrigin(window.location.origin), []);
  const https = `${origin}${feedUrl}`;
  const webcal = https.replace(/^https?:/, 'webcal:');
  return (
    <section aria-labelledby="subscribe-title" className="space-y-2 rounded-md border p-4 text-sm">
      <h2 id="subscribe-title" className="font-medium">
        {t(copy.title)}
      </h2>
      <p className="text-muted-foreground">{t(copy.hint)}</p>
      <p>
        <a href={webcal} className="underline">
          {t(copy.webcal)}
        </a>
      </p>
      <p className="flex items-center gap-2">
        <input
          readOnly
          aria-label={t(copy.feed)}
          value={https}
          className="w-full min-w-0 rounded border px-2 py-1"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={async () => {
            await navigator.clipboard?.writeText(https);
            setCopied(true);
          }}
        >
          {copied ? t(copy.copied) : t(copy.copy)}
        </Button>
      </p>
    </section>
  );
}
