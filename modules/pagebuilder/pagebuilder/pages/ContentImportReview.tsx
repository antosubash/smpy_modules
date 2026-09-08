import { Head, Link, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { NoteDialog } from '../components/NoteDialog';
import { ImportPlanSummary } from '../components/snapshots/ImportPlanSummary';
import { approveImport, type PendingImport, rejectImport } from '../utils/snapshotsApi';

interface Props {
  pending: PendingImport | null;
}

const CONTENT_URL = '/pagebuilder/content';

/**
 * The approval gate: what this restore would do, and the decision.
 *
 * Applying is confirmed at `medium` rather than `high` because it is genuinely
 * reversible — a `pre_restore` snapshot is taken automatically first, so the
 * previous state is one restore away. Demanding a typed phrase here would
 * overstate the risk, and a confirmation that overstates gets clicked through.
 */
export default function ContentImportReview() {
  const { pending } = usePage<{ props: Props }>().props as unknown as Props;
  const [error, setError] = useState<string | null>(null);

  if (!pending) {
    return (
      <AuthenticatedLayout>
        <Head title="Review import" />
        <PageShell title="Review import" description="Nothing is waiting for approval.">
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            No import is staged. Pick a snapshot and choose Restore to stage one.
          </p>
          <div className="mt-4">
            <Button asChild variant="outline">
              <Link href={CONTENT_URL}>Back to snapshots</Link>
            </Button>
          </div>
        </PageShell>
      </AuthenticatedLayout>
    );
  }

  const apply = async () => {
    try {
      const result = await approveImport(pending.id);
      toast.success('Snapshot restored', {
        description:
          `${result.pages_created} created, ${result.pages_updated} updated. ` +
          'A snapshot of the previous state was taken first.',
      });
      router.visit(CONTENT_URL);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Apply failed';
      setError(message);
      throw e;
    }
  };

  return (
    <AuthenticatedLayout>
      <Head title="Review import" />
      <PageShell
        title="Review import"
        description={`Snapshot #${pending.snapshot_id}, staged by ${pending.created_by ?? 'someone'}.`}
        actions={
          <div className="flex items-center gap-2">
            <NoteDialog
              trigger={<Button variant="outline">Reject</Button>}
              title="Reject this import"
              description="The staged restore is discarded. The site is untouched either way."
              label="Why?"
              placeholder="Wrong bundle, stale content, …"
              submitLabel="Reject"
              required
              onSubmit={async (note) => {
                await rejectImport(pending.id, note);
                router.visit(CONTENT_URL);
              }}
            />
            <ConfirmDialog
              trigger={<Button>Approve &amp; apply</Button>}
              title="Apply this snapshot?"
              description={
                <>
                  A snapshot of the site as it stands right now is taken first, so this can be
                  undone by restoring that one.
                </>
              }
              confirmLabel="Apply"
              level="medium"
              onConfirm={apply}
            />
          </div>
        }
      >
        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
        <ImportPlanSummary plan={pending.plan} />
      </PageShell>
    </AuthenticatedLayout>
  );
}
