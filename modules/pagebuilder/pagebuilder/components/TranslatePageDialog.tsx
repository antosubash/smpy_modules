import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';

import type { PageRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { localeLabel, publicPath } from '../utils/locale';
import { createTranslation, getPage } from '../utils/pagesApi';

const LOCALE_ID = 'translate-page-locale';
const COPY_ID = 'translate-page-copy';

interface Props {
  page: PageRead;
  /** Every language the site publishes in. */
  locales: string[];
  defaultLocale: string;
  publicPrefix: string;
}

/**
 * Duplicate a page into a language it does not exist in yet.
 *
 * The editor's Languages tab can do this too, but only once you are already
 * inside the page — three levels down from the list an author is looking at
 * when they think "we need this in German". This is the same operation on the
 * row itself.
 *
 * Which languages are still free is asked of the server when the dialog opens
 * rather than guessed from the rows on screen: the list is paged, so a
 * counterpart can easily be on a page the browser has not loaded, and offering
 * a language that already exists turns one click into a 409.
 */
export function TranslatePageDialog({ page, locales, defaultLocale, publicPrefix }: Props) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [missing, setMissing] = useState<string[] | null>(null);
  const [target, setTarget] = useState('');
  const [copyContent, setCopyContent] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setMissing(null);
    setError(null);
    void getPage(page.id, controller.signal)
      .then((detail) => {
        if (controller.signal.aborted) return;
        const taken = new Set(detail.translations.map((t) => t.locale));
        const free = locales.filter((l) => !taken.has(l));
        setMissing(free);
        setTarget(free[0] ?? '');
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message);
      });
    return () => controller.abort();
  }, [open, page.id, locales]);

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      const created = await createTranslation(page.id, {
        locale: target,
        copy_content: copyContent,
      });
      // Straight into the new page: the next thing to do is translate it.
      router.visit(`/pagebuilder/${created.id}/edit`);
    } catch (e) {
      setError((e as Error).message);
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="link" size="sm" data-testid={`translate-page-${page.id}`}>
          {t(keys.pagebuilder.translate.trigger)}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (target && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(keys.pagebuilder.translate.title, { title: page.title })}</DialogTitle>
            <DialogDescription>{t(keys.pagebuilder.translate.description)}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {missing === null && !error && (
              <p className="text-sm text-muted-foreground">
                {t(keys.pagebuilder.translate.checking)}
              </p>
            )}

            {missing?.length === 0 && (
              <p className="text-sm" data-testid="translate-page-none-left">
                {t(keys.pagebuilder.translate.none_left)}
              </p>
            )}

            {missing && missing.length > 0 && (
              <>
                <div className="grid gap-2">
                  <Label htmlFor={LOCALE_ID}>{t(keys.pagebuilder.translate.language)}</Label>
                  <NativeSelect
                    id={LOCALE_ID}
                    value={target}
                    disabled={pending}
                    onChange={(e) => setTarget(e.target.value)}
                  >
                    {missing.map((tag) => (
                      <option key={tag} value={tag}>
                        {localeLabel(tag)}
                      </option>
                    ))}
                  </NativeSelect>
                  {/* The address is a <code> span inside the sentence, so the
                      two halves are separate keys rather than one with a
                      placeholder. */}
                  <p className="text-xs text-muted-foreground">
                    {t(keys.pagebuilder.translate.address_before)}{' '}
                    <code>{publicPath(publicPrefix, page.slug, target, defaultLocale)}</code>{' '}
                    {t(keys.pagebuilder.translate.address_after)}
                  </p>
                </div>

                <div className="flex items-start gap-2">
                  <Checkbox
                    id={COPY_ID}
                    checked={copyContent}
                    disabled={pending}
                    onCheckedChange={(v) => setCopyContent(v === true)}
                  />
                  <div className="grid gap-1">
                    <Label htmlFor={COPY_ID}>{t(keys.pagebuilder.translate.copy_label)}</Label>
                    <p className="text-xs text-muted-foreground">
                      {t(keys.pagebuilder.translate.copy_help)}
                    </p>
                  </div>
                </div>
              </>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setOpen(false)}
            >
              {t(keys.pagebuilder.translate.cancel)}
            </Button>
            <Button type="submit" disabled={pending || !target}>
              {pending
                ? t(keys.pagebuilder.translate.creating)
                : t(keys.pagebuilder.translate.create)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
