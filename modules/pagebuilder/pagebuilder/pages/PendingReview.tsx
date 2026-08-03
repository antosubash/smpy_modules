import { router, usePage } from '@inertiajs/react';
import { useState } from 'react';

import { approvePage, promptAndReject, type PageRead } from '../utils/api';

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
    <div className="max-w-5xl mx-auto p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Pending review</h1>
        <button
          type="button"
          onClick={() => router.visit('/pagebuilder')}
          className="text-blue-600 hover:underline text-sm"
        >
          ← All pages
        </button>
      </div>

      {message && <p className="mb-4 text-sm text-red-700">{message}</p>}

      {pages.items.length === 0 ? (
        <div className="text-gray-500 border border-dashed rounded p-8 text-center">
          No pages are awaiting review.
        </div>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b text-left text-sm text-gray-600">
              <th className="py-2 pr-4">Title</th>
              <th className="py-2 pr-4">Slug</th>
              <th className="py-2 pr-4">Submitted</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.items.map((p) => (
              <tr key={p.id} className="border-b hover:bg-gray-50">
                <td className="py-3 pr-4 font-medium">{p.title}</td>
                <td className="py-3 pr-4 text-gray-600 font-mono text-sm">{p.slug}</td>
                <td className="py-3 pr-4 text-sm text-gray-600">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </td>
                <td className="py-3 text-right space-x-3">
                  <button
                    type="button"
                    onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}
                    className="text-blue-600 hover:underline text-sm"
                  >
                    Review
                  </button>
                  <button
                    type="button"
                    disabled={busy === p.id}
                    onClick={() => handleApprove(p.id)}
                    className="text-green-700 hover:underline text-sm disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={busy === p.id}
                    onClick={() => handleReject(p.id)}
                    className="text-red-600 hover:underline text-sm disabled:opacity-50"
                  >
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
