import { Head, router, usePage } from '@inertiajs/react';
import { ConfirmActionDialog } from '@simple-module-py/ui/components/ConfirmActionDialog';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import { Archive, Plus } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { AdminNav } from '../components/AdminNav';
import { PlanEditor } from '../components/PlanEditor';
import { PlansTable } from '../components/PlansTable';
import { ADMIN_API, api } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { type PlanForm, planPayload } from '../utils/plan-form';
import type { AdminCommon, Plan } from '../utils/types';

interface Props extends AdminCommon {
  plans: Plan[];
  known_limit_keys: string[];
}

function Plans() {
  const { t } = useT();
  const c = keys.billing.plans;
  const { plans, known_limit_keys, csrf_token, can_manage } = usePage<{ props: Props }>()
    .props as unknown as Props;
  const [editing, setEditing] = useState<Plan | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [archiving, setArchiving] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Synchronous in-flight guard: `busy` state only lands on the next render,
  // so a fast double click would otherwise send two POSTs.
  const inFlight = useRef(false);

  async function run(work: () => Promise<void>, onError?: (message: string) => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
      router.reload();
    } catch (err) {
      const message = (err as Error).message;
      onError?.(message);
      toast.error(message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const open = (plan: Plan | null) => {
    setEditing(plan);
    setSaveError(null);
    setEditorOpen(true);
  };

  const save = (form: PlanForm) =>
    run(async () => {
      setSaveError(null);
      const body = planPayload(form);
      if (editing) {
        await api(`${ADMIN_API}/plans/${editing.id}`, csrf_token, { method: 'PUT', body });
      } else {
        await api(`${ADMIN_API}/plans`, csrf_token, { body });
      }
      toast.success(editing ? t(c.saved) : t(c.created));
      setEditorOpen(false);
    }, setSaveError);

  const archive = () =>
    run(async () => {
      if (!archiving) return;
      await api(`${ADMIN_API}/plans/${archiving.id}/archive`, csrf_token, { body: {} });
      toast.success(t(c.archived, { name: archiving.name }));
      setArchiving(null);
    });

  return (
    <>
      <Head title={t(c.head_title)} />
      <PageShell
        title={t(keys.billing.page.title)}
        description={t(c.description)}
        actions={
          can_manage ? (
            <Button onClick={() => open(null)}>
              <Plus aria-hidden="true" /> {t(c.new_plan)}
            </Button>
          ) : undefined
        }
      >
        <AdminNav active="plans" />
        <Card className="overflow-hidden p-0">
          <PlansTable plans={plans} canManage={can_manage} onEdit={open} onArchive={setArchiving} />
        </Card>
      </PageShell>
      <PlanEditor
        open={editorOpen}
        plan={editing}
        knownKeys={known_limit_keys}
        busy={busy}
        serverError={saveError}
        onOpenChange={setEditorOpen}
        onSave={save}
      />
      <ConfirmActionDialog
        open={archiving !== null}
        onOpenChange={(o) => !o && setArchiving(null)}
        icon={Archive}
        title={t(c.archive_title, { name: archiving?.name ?? '' })}
        description={t(c.archive_description)}
        confirmLabel={t(c.archive)}
        cancelLabel={t(c.cancel)}
        busy={busy}
        onConfirm={archive}
      />
    </>
  );
}

Plans.layout = [AdminLayout];
export default Plans;
