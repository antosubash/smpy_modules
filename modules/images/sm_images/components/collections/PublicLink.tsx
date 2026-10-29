import { Button } from '@simple-module-py/ui/components/ui/button';
import { toast } from 'sonner';

import { keys, useT } from '../../utils/i18n';

/** A public collection's page (`path`, from the server) as a link on this
 *  host, with a button that copies it. */
export function PublicLink({ path }: { path: string }) {
  const { t } = useT();
  const url = new URL(path, window.location.origin).toString();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast(t(keys.images.visibility.link_copied));
    } catch {
      toast.error(t(keys.images.visibility.link_copy_failed));
    }
  };
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">{t(keys.images.visibility.public_link)}</span>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="min-w-0 break-all text-primary hover:underline"
        data-testid="images-public-link"
      >
        {url}
      </a>
      <Button
        type="button"
        size="sm"
        variant="outline"
        data-testid="images-public-link-copy"
        onClick={() => void copy()}
      >
        {t(keys.images.visibility.copy_link)}
      </Button>
    </div>
  );
}
