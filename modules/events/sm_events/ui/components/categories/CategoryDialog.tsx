import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type FormEvent, useState } from 'react';
import { createCategory, errorText, updateCategory } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { type Category, DEFAULT_COLOR } from '../../utils/types';

export function CategoryDialog({
  category,
  contentLocales,
  onSaved,
}: {
  category?: Category;
  contentLocales: string[];
  onSaved: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={category ? 'outline' : 'default'}>
          {t(category ? keys.events.common.edit : keys.events.categories.new)}
        </Button>
      </DialogTrigger>
      {open && (
        <CategoryForm
          category={category}
          contentLocales={contentLocales}
          onSaved={() => {
            onSaved();
            setOpen(false);
          }}
        />
      )}
    </Dialog>
  );
}
function CategoryForm({
  category,
  contentLocales,
  onSaved,
}: {
  category?: Category;
  contentLocales: string[];
  onSaved: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.categories;
  const [names, setNames] = useState(category?.names ?? {});
  const [slug, setSlug] = useState(category?.slug ?? '');
  const [color, setColor] = useState<string | null>(category ? category.color : DEFAULT_COLOR);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const body = {
      names: Object.fromEntries(
        contentLocales
          .filter((locale) => names[locale]?.trim())
          .map((locale) => [locale, names[locale].trim()]),
      ),
      color,
    };
    try {
      if (category) await updateCategory(category.id, body);
      else await createCategory({ ...body, ...(slug ? { slug } : {}) });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <DialogContent
      className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
      showCloseButton={false}
      onEscapeKeyDown={(e) => {
        if (pending) e.preventDefault();
      }}
      onInteractOutside={(e) => {
        if (pending) e.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{t(category ? copy.edit : copy.new)}</DialogTitle>
        <DialogDescription>{t(copy.form_description)}</DialogDescription>
      </DialogHeader>
      <form className="grid gap-4" onSubmit={save}>
        {contentLocales.map((locale, index) => (
          <div key={locale} className="grid gap-2">
            <Label htmlFor={`category-name-${locale}`}>{t(copy.name, { locale })}</Label>
            <Input
              id={`category-name-${locale}`}
              required={index === 0}
              maxLength={100}
              value={names[locale] ?? ''}
              onChange={(e) => setNames({ ...names, [locale]: e.target.value })}
            />
          </div>
        ))}
        <div className="grid gap-2">
          <Label htmlFor="category-slug">{t(copy.slug)}</Label>
          <Input
            id="category-slug"
            readOnly={!!category}
            maxLength={80}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="category-color">{t(copy.color)}</Label>
          <Input
            id="category-color"
            type="color"
            value={color ?? DEFAULT_COLOR}
            onChange={(e) => setColor(e.target.value)}
          />
          <span>{color ?? t(copy.no_color)}</span>
          <Button type="button" variant="outline" onClick={() => setColor(null)}>
            {t(copy.clear_color)}
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={pending}>
              {t(keys.events.common.cancel)}
            </Button>
          </DialogClose>
          <Button disabled={pending || contentLocales.length === 0}>
            {t(pending ? keys.events.common.saving : keys.events.common.save)}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
