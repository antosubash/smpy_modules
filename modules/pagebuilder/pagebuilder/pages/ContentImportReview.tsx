import { Head, Link, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { NoteDialog } from '../components/NoteDialog';
import { ImportPlanSummary } from '../components/snapshots/ImportPlanSummary';
import { keys, useT } from '../utils/i18n';
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
function ContentImportReview() {
  const { t } = useT();
  const { pending } = usePage<{ props: Props }>().props as unknown as Props;
  const [error, setError] = useState<string | null>(null);

  if (!pending) {
    return (
      <>
        <Head title={t(keys.pagebuilder.import_review.title)} />
        <PageShell
          title={t(keys.pagebuilder.import_review.title)}
          description={t(keys.pagebuilder.import_review.empty_description)}
        >
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t(keys.pagebuilder.import_review.empty)}
          </p>
          <div className="mt-4">
            <Button asChild variant="outline">
              <Link href={CONTENT_URL}>{t(keys.pagebuilder.import_review.back)}</Link>
            </Button>
          </div>
        </PageShell>
      </>
    );
  }

  const apply = async () => {
    try {
      const result = await approveImport(pending.id);
      toast.success(t(keys.pagebuilder.import_review.applied), {
        description: t(keys.pagebuilder.import_review.applied_description, {
          created: result.pages_created,
          updated: result.pages_updated,
        }),
      });
      router.visit(CONTENT_URL);
    } catch (e) {
      const message =
        e instanceof Error ? e.message : t(keys.pagebuilder.import_review.apply_failed);
      setError(message);
      throw e;
    }
  };

  return (
    <>
      <Head title={t(keys.pagebuilder.import_review.title)} />
      <PageShell
        title={t(keys.pagebuilder.import_review.title)}
        description={t(keys.pagebuilder.import_review.description, {
          id: pending.snapshot_id,
          author: pending.created_by ?? t(keys.pagebuilder.import_review.someone),
        })}
        actions={
          <div className="flex items-center gap-2">
            <NoteDialog
              trigger={
                <Button variant="outline">{t(keys.pagebuilder.import_review.reject)}</Button>
              }
              title={t(keys.pagebuilder.import_review.reject_title)}
              description={t(keys.pagebuilder.import_review.reject_description)}
              label={t(keys.pagebuilder.import_review.reject_label)}
              placeholder={t(keys.pagebuilder.import_review.reject_placeholder)}
              submitLabel={t(keys.pagebuilder.import_review.reject)}
              required
              onSubmit={async (note) => {
                await rejectImport(pending.id, note);
                router.visit(CONTENT_URL);
              }}
            />
            <ConfirmDialog
              trigger={<Button>{t(keys.pagebuilder.import_review.approve)}</Button>}
              title={t(keys.pagebuilder.import_review.approve_title)}
              description={t(keys.pagebuilder.import_review.approve_description)}
              confirmLabel={t(keys.pagebuilder.import_review.apply)}
              level="medium"
              onConfirm={apply}
            />
          </div>
        }
      >
        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
        <ImportPlanSummary plan={pending.plan} />
      </PageShell>
    </>
  );
}

ContentImportReview.layout = [AuthenticatedLayout];
export default ContentImportReview;
