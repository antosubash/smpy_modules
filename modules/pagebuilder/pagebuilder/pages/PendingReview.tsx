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
import { useState } from 'react';

import { approvePage, type PageRead, promptAndReject } from '../utils/api';

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
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const handleApprove = async (id: number) => {
    if (!confirm('Approve and publish this page?')) return;
    setBusy(id);
    setMessage(null);
    try {
      await approvePage(id);
      router.reload({ only: ['pages'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Approve failed');
    } finally {
      setBusy(null);
    }
  };

  const handleReject = async (id: number) => {
    setBusy(id);
    setMessage(null);
    const result = await promptAndReject(id);
    setBusy(null);
    if ('skipped' in result) {
      if (result.skipped !== 'cancelled') setMessage(result.skipped);
      return;
    }
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
      {message && <p className="mb-4 text-sm text-destructive">{message}</p>}

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
                  <Button
                    variant="link"
                    size="sm"
                    disabled={busy === p.id}
                    onClick={() => handleApprove(p.id)}
                  >
                    Approve
                  </Button>
                  <Button
                    variant="link"
                    size="sm"
                    className="text-destructive"
                    disabled={busy === p.id}
                    onClick={() => handleReject(p.id)}
                  >
                    Reject
                  </Button>
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
