import { Button } from '@simple-module-py/ui/components/ui/button';
import type { CreatedFeedToken } from '../../utils/api-feeds';
import { keys, useT } from '../../utils/i18n';
import { CopyButton } from '../CopyButton';

/** The link, shown once. It lives in the parent's state for as long as this is on screen and is
 *  never written to the address bar, storage, a toast or the console. The input is selectable
 *  for a browser without clipboard access. */
export function CreatedLink({ link, onDone }: { link: CreatedFeedToken; onDone: () => void }) {
  const { t } = useT();
  const copy = keys.events.feeds;
  return (
    <section className="space-y-2 rounded-md border p-3" aria-label={t(copy.created_title)}>
      <h3 className="text-sm font-medium">{t(copy.created_title)}</h3>
      <p className="text-sm font-medium text-destructive" role="status">
        {t(copy.created_warning)}
      </p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          aria-label={t(copy.link)}
          value={link.url}
          onFocus={(e) => e.currentTarget.select()}
          className="w-full min-w-0 rounded border px-2 py-1 text-sm"
        />
        <CopyButton text={link.url} />
      </div>
      <p className="text-sm">
        <a href={link.webcal_url} className="underline">
          {t(copy.webcal)}
        </a>
      </p>
      <Button type="button" size="sm" onClick={onDone}>
        {t(copy.done)}
      </Button>
    </section>
  );
}
