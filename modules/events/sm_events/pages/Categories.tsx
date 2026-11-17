import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { ConfirmDialog } from '../ui/components/ConfirmDialog';
import { CategoryDialog } from '../ui/components/categories/CategoryDialog';
import { useCategories } from '../ui/hooks/useCategories';
import { deleteCategory } from '../ui/utils/api';
import { categoryName } from '../ui/utils/categories';
import { keys, useT } from '../ui/utils/i18n';
import { Name, withName } from '../ui/utils/isolate';

/** A long unbroken name must wrap inside the cell, not widen the table. */
const WRAP = 'max-w-xs whitespace-normal [overflow-wrap:anywhere]';
const NAME = `min-w-48 ${WRAP}`;

export default function Categories({ content_locales }: { content_locales: string[] }) {
  const { t, locale } = useT();
  const copy = keys.events.categories;
  const list = useCategories();
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell
        title={t(copy.title)}
        description={t(copy.subtitle)}
        actions={<CategoryDialog contentLocales={content_locales} onSaved={list.reload} />}
      >
        <div className="space-y-4">
          {list.error && (
            <p role="alert" className="text-destructive">
              {list.error}
            </p>
          )}
          {list.loading && <p role="status">{t(keys.events.common.loading)}</p>}
          <div className="max-w-full overflow-x-auto">
            <Table aria-label={t(copy.title)}>
              <TableHeader>
                <TableRow>
                  <TableHead>{t(copy.color)}</TableHead>
                  <TableHead>{t(copy.col_slug)}</TableHead>
                  {content_locales.map((locale) => (
                    <TableHead key={locale}>{t(copy.name, { locale })}</TableHead>
                  ))}
                  <TableHead>{t(copy.actions)}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.items.map((category) => {
                  const name = categoryName(category, locale, content_locales);
                  return (
                    <TableRow key={category.id}>
                      <TableCell>
                        {category.color && (
                          <span
                            aria-hidden="true"
                            className="mr-2 inline-block size-3 rounded-full border"
                            style={{ backgroundColor: category.color }}
                          />
                        )}
                        {category.color ?? t(copy.no_color)}
                      </TableCell>
                      <TableCell className={WRAP}>{category.slug}</TableCell>
                      {content_locales.map((locale) => (
                        <TableCell key={locale} className={NAME}>
                          {category.names[locale] ? (
                            <Name>{category.names[locale]}</Name>
                          ) : (
                            t(copy.no_name)
                          )}
                        </TableCell>
                      ))}
                      <TableCell>
                        <div className="flex gap-2 whitespace-nowrap">
                          <CategoryDialog
                            category={category}
                            label={t(copy.edit_for, { name })}
                            contentLocales={content_locales}
                            onSaved={list.reload}
                          />
                          <ConfirmDialog
                            trigger={
                              <Button variant="outline" aria-label={t(copy.delete_for, { name })}>
                                {t(copy.delete)}
                              </Button>
                            }
                            title={withName(t, copy.delete_title, name)}
                            description={t(copy.delete_description)}
                            confirmLabel={t(copy.delete)}
                            onConfirm={async () => {
                              await deleteCategory(category.id);
                              list.reload();
                            }}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {!list.loading && !list.error && list.items.length === 0 && <p>{t(copy.empty)}</p>}
        </div>
      </PageShell>
    </>
  );
}
Categories.layout = [AuthenticatedLayout];
