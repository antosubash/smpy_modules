import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { Outcome } from '../../hooks/useEventActions';
import { formatInstant } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import type { EventDetail, WorkflowAction, WorkflowBody } from '../../utils/types-events';
import { RejectDialog } from './RejectDialog';
import { ScheduleDialog } from './ScheduleDialog';

type Rights = Pick<EventDetail, 'status' | 'scheduled' | 'can_write' | 'can_publish'>;

/** The actions the API will accept for this event and caller, and no others
 *  (`sm_events/content/workflow.py`: every action needs the write right on the
 *  calendar, `TRANSITIONS` marks the ones that also need `events.publish`). A
 *  scheduled event can only be unscheduled. So `can_publish` alone offers nothing. */
export function workflowActions(e: Rights): WorkflowAction[] {
  if (!e.can_write) return [];
  const publish = e.can_publish;
  if (e.scheduled) return publish ? ['unschedule'] : [];
  if (e.status === 'draft') return publish ? ['submit', 'approve'] : ['submit'];
  if (e.status === 'in_review') {
    return publish ? ['withdraw', 'approve', 'reject'] : ['withdraw'];
  }
  return publish ? ['unpublish'] : [];
}

type Run = (
  action: WorkflowAction,
  body?: Omit<WorkflowBody, 'expected_revision'>,
  onError?: (e: unknown) => void,
) => Promise<Outcome>;

/** The status, and the workflow actions the caller may take on it. They apply
 *  to the saved event, so they wait for unsaved edits to be saved or discarded. */
export function WorkflowBar({
  event,
  dirty,
  busy,
  run,
}: {
  event: EventDetail;
  dirty: boolean;
  busy: boolean;
  run: Run;
}) {
  const { t, locale } = useT();
  const copy = keys.events.workflow;
  const actions = workflowActions(event);
  const off = dirty || busy;
  const status = event.scheduled ? 'scheduled' : event.status;
  const plain = (action: WorkflowAction, label: string) => (
    <Button key={action} variant="outline" disabled={off} onClick={() => void run(action)}>
      {label}
    </Button>
  );
  return (
    <section
      className="flex flex-wrap items-center gap-3 rounded-md border p-3"
      aria-label={t(copy.title)}
    >
      <span className="text-sm">{t(copy.status)}</span>
      <Badge variant={status === 'published' ? 'default' : 'secondary'}>
        {t(keys.events.list[`status_${status}`])}
      </Badge>
      {event.cancelled && <Badge variant="destructive">{t(keys.events.list.cancelled)}</Badge>}
      {event.scheduled && event.publish_at && (
        <span className="text-sm text-muted-foreground dark:text-zinc-400">
          {t(copy.scheduled_for, { when: formatInstant(event.publish_at, event.timezone, locale) })}
        </span>
      )}
      <span className="ml-auto flex flex-wrap gap-2">
        {actions.map((action) => {
          if (action === 'approve') {
            return (
              <ScheduleDialog
                key={action}
                disabled={off}
                timezone={event.timezone}
                onApprove={(body, onError) => run('approve', body, onError)}
              />
            );
          }
          if (action === 'reject') {
            return (
              <RejectDialog
                key={action}
                disabled={off}
                onReject={(body, onError) => run('reject', body, onError)}
              />
            );
          }
          return plain(action, t(copy[action]));
        })}
      </span>
      {dirty && actions.length > 0 && (
        <p className="basis-full text-sm text-muted-foreground dark:text-zinc-400">
          {t(copy.save_first)}
        </p>
      )}
    </section>
  );
}
