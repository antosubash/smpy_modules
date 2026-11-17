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
import { type FormEvent, useMemo, useState } from 'react';
import { useFormErrors } from '../../hooks/useFormErrors';
import { createCategory, updateCategory } from '../../utils/api';
import { requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import { type Category, DEFAULT_COLOR } from '../../utils/types';
import { FieldError, invalidProps } from '../FieldError';

export function CategoryDialog({
  category,
  label,
  contentLocales,
  onSaved,
}: {
  category?: Category;
  /** The trigger's accessible name, which says which row it acts on. */
  label?: string;
  contentLocales: string[];
  onSaved: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={category ? 'outline' : 'default'} aria-label={label}>
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
  // The 422 paths this form can show: each locale's own input, the whole map's
  // group message, and the fields below.
  const shown = useMemo(
    () => ['names', 'slug', 'color', ...contentLocales.map((l) => `names.${l}`)],
    [contentLocales],
  );
  const errors = useFormErrors(undefined, undefined, shown);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    const first = contentLocales[0];
    if (first && !names[first]?.trim()) {
      errors.setField(`names.${first}`, requiredText());
      return;
    }
    setPending(true);
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
      errors.fail(e);
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
      <form className="grid gap-4" noValidate onSubmit={save}>
        {contentLocales.map((locale, index) => {
          const id = `category-name-${locale}`;
          const message = errors.fields[`names.${locale}`];
          return (
            <div key={locale} className="grid gap-2">
              <Label htmlFor={id}>{t(copy.name, { locale })}</Label>
              <Input
                id={id}
                required={index === 0}
                maxLength={100}
                value={names[locale] ?? ''}
                {...invalidProps(id, message)}
                onChange={(e) => {
                  setNames({ ...names, [locale]: e.target.value });
                  errors.clearField(`names.${locale}`);
                  errors.clearField('names');
                }}
              />
              <FieldError id={id} message={message} />
            </div>
          );
        })}
        <FieldError id="category-names" message={errors.fields.names} />
        <div className="grid gap-2">
          <Label htmlFor="category-slug">{t(copy.slug)}</Label>
          <Input
            id="category-slug"
            readOnly={!!category}
            maxLength={80}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            value={slug}
            {...invalidProps('category-slug', errors.fields.slug)}
            onChange={(e) => {
              setSlug(e.target.value);
              errors.clearField('slug');
            }}
          />
          <FieldError id="category-slug" message={errors.fields.slug} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="category-color">{t(copy.color)}</Label>
          {color === null ? (
            <>
              <span>{t(copy.no_color)}</span>
              <Button type="button" variant="outline" onClick={() => setColor(DEFAULT_COLOR)}>
                {t(copy.choose_color)}
              </Button>
            </>
          ) : (
            <>
              <Input
                id="category-color"
                type="color"
                value={color}
                {...invalidProps('category-color', errors.fields.color)}
                onChange={(e) => {
                  setColor(e.target.value);
                  errors.clearField('color');
                }}
              />
              <span>{color}</span>
              <Button type="button" variant="outline" onClick={() => setColor(null)}>
                {t(copy.clear_color)}
              </Button>
            </>
          )}
          <FieldError id="category-color" message={errors.fields.color} />
        </div>
        {errors.error && (
          <p role="alert" className="text-destructive">
            {errors.error}
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
