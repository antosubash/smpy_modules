import { router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
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
          <button
            type="button"
            onClick={() => router.visit('/pagebuilder/pending')}
            className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
          >
            Pending review
          </button>
          <button
            type="button"
            onClick={() => router.visit('/pagebuilder/layout')}
            className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
          >
            Site layout
          </button>
          <button
            type="button"
            onClick={() => router.visit('/pagebuilder/media')}
            className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
          >
            Media library
          </button>
          <button
            type="button"
            onClick={() => router.visit('/pagebuilder/new')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
          >
            New page
          </button>
        </>
      }
    >
      {pages.items.length === 0 ? (
        <div className="text-gray-500 border border-dashed rounded p-8 text-center">
          No pages yet. Click "New page" to create your first one.
        </div>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b text-left text-sm text-gray-600">
              <th className="py-2 pr-4">Title</th>
              <th className="py-2 pr-4">Slug</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Updated</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.items.map((p) => (
              <tr key={p.id} className="border-b hover:bg-gray-50">
                <td className="py-3 pr-4 font-medium">{p.title}</td>
                <td className="py-3 pr-4 text-gray-600 font-mono text-sm">{p.slug}</td>
                <td className="py-3 pr-4">
                  <StatusBadge status={p.status} />
                  <ScheduledBadge
                    status={p.status}
                    publishAt={p.publish_at}
                    unpublishAt={p.unpublish_at}
                  />
                </td>
                <td className="py-3 pr-4 text-sm text-gray-600">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </td>
                <td className="py-3 text-right space-x-2">
                  {p.status === 'published' && (
                    <a
                      href={`/p/${p.slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline text-sm"
                    >
                      View
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}
                    className="text-blue-600 hover:underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    disabled={busy === p.id}
                    onClick={() => handleDelete(p.id)}
                    className="text-red-600 hover:underline text-sm disabled:opacity-50"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </PageShell>
  );
}

PageList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
