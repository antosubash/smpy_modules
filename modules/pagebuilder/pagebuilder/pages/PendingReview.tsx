import { router, usePage } from '@inertiajs/react';
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

import { ConfirmDialog } from '../components/ConfirmDialog';
import { NoteDialog } from '../components/NoteDialog';
import { approvePage, type PageRead, rejectPage } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { publicPath } from '../utils/locale';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`. */
const PUBLIC_PREFIX = '/p';

interface Props {
  pages: { items: PageRead[] };
  /** The language that serves unprefixed, so the approve confirmation names
   *  the address this page will actually take. */
  default_locale?: string;
}

/**
 * Approver-only queue showing pages currently in
 * ``submitted_for_review``. Approve takes the page live; reject sends
 * it back to draft with a required rationale (surfaced to editors in
 * the editor header + history panel).
 */
export default function PendingReview() {
  const { t } = useT();
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { pages } = props;
  const defaultLocale = props.default_locale ?? 'en';

  // Both handlers let their error escape into the dialog that triggered them,
  // which keeps the message next to the row it belongs to. The page-level
  // banner these used to write to sat above a queue of near-identical rows and
  // never said which one had failed.
  const handleApprove = async (id: number) => {
    await approvePage(id);
    router.reload({ only: ['pages'] });
  };

  const handleReject = async (id: number, note: string) => {
    await rejectPage(id, note);
    router.reload({ only: ['pages'] });
  };

  return (
    <PageShell
      title={t(keys.pagebuilder.pending.title)}
      description={t(keys.pagebuilder.pending.description)}
      actions={
        <Button variant="outline" onClick={() => router.visit('/pagebuilder')}>
          {t(keys.pagebuilder.pending.back)}
        </Button>
      }
    >
      {pages.items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          {t(keys.pagebuilder.pending.empty)}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t(keys.pagebuilder.pending.column_title)}</TableHead>
              <TableHead>{t(keys.pagebuilder.pending.column_slug)}</TableHead>
              <TableHead>{t(keys.pagebuilder.pending.column_submitted)}</TableHead>
              <TableHead className="text-right">
                {t(keys.pagebuilder.pending.column_actions)}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pages.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.title}</TableCell>
                <TableCell className="font-mono text-sm text-muted-foreground">{p.slug}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button
                    variant="link"
                    size="sm"
                    onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}
                  >
                    {t(keys.pagebuilder.pending.review)}
                  </Button>
                  <ConfirmDialog
                    trigger={
                      <Button variant="link" size="sm">
                        {t(keys.pagebuilder.pending.approve)}
                      </Button>
                    }
                    title={t(keys.pagebuilder.pending.approve_title, { title: p.title })}
                    description={t(keys.pagebuilder.pending.approve_description, {
                      url: publicPath(PUBLIC_PREFIX, p.slug, p.locale, defaultLocale),
                    })}
                    confirmLabel={t(keys.pagebuilder.pending.approve)}
                    onConfirm={() => handleApprove(p.id)}
                  />
                  <NoteDialog
                    trigger={
                      <Button variant="link" size="sm" className="text-destructive">
                        {t(keys.pagebuilder.pending.reject)}
                      </Button>
                    }
                    title={t(keys.pagebuilder.pending.reject_title, { title: p.title })}
                    description={t(keys.pagebuilder.pending.reject_description)}
                    label={t(keys.pagebuilder.pending.reject_label)}
                    placeholder={t(keys.pagebuilder.pending.reject_placeholder)}
                    submitLabel={t(keys.pagebuilder.pending.reject)}
                    required
                    destructive
                    onSubmit={(note) => handleReject(p.id, note)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </PageShell>
  );
}

PendingReview.layout = [AuthenticatedLayout];
