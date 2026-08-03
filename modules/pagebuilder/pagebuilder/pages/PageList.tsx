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

import { ScheduledBadge } from '../components/ScheduledBadge';
import { StatusBadge } from '../components/StatusBadge';
import { deletePage, type PageRead } from '../utils/api';

interface Props {
  pages: { items: PageRead[] };
}

export default function PageList() {
  const { pages } = usePage<{ props: Props }>().props as unknown as Props;
  const [busy, setBusy] = useState<number | null>(null);

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this page?')) return;
    setBusy(id);
    try {
      await deletePage(id);
      router.reload({ only: ['pages'] });
    } finally {
      setBusy(null);
    }
  };

  return (
    <PageShell
      title="Pages"
      description="Compose, review, and publish site pages."
      actions={
        <>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/pending')}>
            Pending review
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/layout')}>
            Site layout
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
            Media library
          </Button>
          <Button onClick={() => router.visit('/pagebuilder/new')}>New page</Button>
        </>
      }
    >
      {pages.items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No pages yet. Click "New page" to create your first one.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pages.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.title}</TableCell>
                <TableCell className="font-mono text-sm text-muted-foreground">{p.slug}</TableCell>
                <TableCell>
                  <span className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={p.status} />
                    <ScheduledBadge
                      status={p.status}
                      publishAt={p.publish_at}
                      unpublishAt={p.unpublish_at}
                    />
                  </span>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  {/* Stays an <a>: the e2e selects it with getByRole('link'). */}
                  {p.status === 'published' && (
                    <a
                      href={`/p/${p.slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-primary hover:underline"
                    >
                      View
                    </a>
                  )}
                  <Button
                    variant="link"
                    size="sm"
                    onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="link"
                    size="sm"
                    className="text-destructive"
                    disabled={busy === p.id}
                    onClick={() => handleDelete(p.id)}
                  >
                    Delete
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

PageList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
