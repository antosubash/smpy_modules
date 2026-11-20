import { useEffect, useState } from 'react';
import { CopyButton } from '../components/CopyButton';
import { keys, useT } from '../utils/i18n';

/** The feed's `https` address, a `webcal:` link that opens the calendar app, and a copy button.
 *  The origin is the page's own, read after mount (the server renders the path). */
export function SubscribeBox({ feedUrl }: { feedUrl: string }) {
  const { t } = useT();
  const copy = keys.events.public.subscribe;
  const [origin, setOrigin] = useState('');
  useEffect(() => setOrigin(window.location.origin), []);
  const https = `${origin}${feedUrl}`;
  const webcal = https.replace(/^https?:/, 'webcal:');
  return (
    <section aria-labelledby="subscribe-title" className="space-y-2 rounded-md border p-4 text-sm">
      <h2 id="subscribe-title" className="font-medium">
        {t(copy.title)}
      </h2>
      <p className="text-muted-foreground dark:text-zinc-400">{t(copy.hint)}</p>
      <p>
        <a href={webcal} className="underline">
          {t(keys.events.feeds.webcal)}
        </a>
      </p>
      <p className="flex items-center gap-2">
        <input
          readOnly
          aria-label={t(copy.feed)}
          value={https}
          className="w-full min-w-0 rounded border px-2 py-1"
        />
        <CopyButton text={https} />
      </p>
    </section>
  );
}
