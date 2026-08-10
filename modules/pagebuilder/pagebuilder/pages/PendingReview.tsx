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
import type React from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { NoteDialog } from '../components/NoteDialog';
import { approvePage, type PageRead, rejectPage } from '../utils/api';

interface Props {
  pages: { items: PageRead[] };
}

/**
 * Approver-only queue showing pages currently in
 * ``submitted_for_review``. Approve takes the page live; reject sends
 * it back to draft with a required rationale (surfaced to editors in
 * the editor header + history panel).
 */
export default function PendingReview() {
  const { pages } = usePage<{ props: Props }>().props as unknown as Props;

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
      title="Pending review"
      description="Pages submitted for approval."
      actions={
        <Button variant="outline" onClick={() => router.visit('/pagebuilder')}>
          ← All pages
        </Button>
      }
    >
      {pages.items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No pages are awaiting review.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Submitted</TableHead>
              <TableHead className="text-right">Actions</TableHead>
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
                    Review
                  </Button>
                  <ConfirmDialog
                    trigger={
                      <Button variant="link" size="sm">
                        Approve
                      </Button>
                    }
                    title={`Publish "${p.title}"?`}
                    description={`Approving publishes it immediately at /p/${p.slug}.`}
                    confirmLabel="Approve"
                    onConfirm={() => handleApprove(p.id)}
                  />
                  <NoteDialog
                    trigger={
                      <Button variant="link" size="sm" className="text-destructive">
                        Reject
                      </Button>
                    }
                    title={`Reject "${p.title}"?`}
                    description="It goes back to draft. The reason is shown to the editor in the page header and the revision history, so say what needs to change."
                    label="Reason for rejection"
                    placeholder="The hero image is still a placeholder."
                    submitLabel="Reject"
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

PendingReview.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
