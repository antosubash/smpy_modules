import { Head, Link } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { EventForm } from '../ui/components/editor/EventForm';
import { OccurrencesPreview } from '../ui/components/editor/OccurrencesPreview';
import { OrphanDialog } from '../ui/components/editor/OrphanDialog';
import { RecurrenceEditor } from '../ui/components/editor/RecurrenceEditor';
import { SubEvents } from '../ui/components/editor/SubEvents';
import { TextsTabs } from '../ui/components/editor/TextsTabs';
import { useEvent } from '../ui/hooks/useEvent';
import { useEventActions } from '../ui/hooks/useEventActions';
import { usePreview } from '../ui/hooks/usePreview';
import { times } from '../ui/utils/event-form';
import { keys, useT } from '../ui/utils/i18n';
import type { Category } from '../ui/utils/types';

type Props = {
  event_id: string | null;
  calendar: { id: string; name: string; default_timezone: string };
  content_locales: string[];
  categories: Category[];
  default_timezone: string;
};

const LIST = '/admin/events/list';

export default function EventEditor(props: Props) {
  const { t } = useT();
  const copy = keys.events.editor;
  const { calendar, content_locales: locales } = props;
  const ev = useEvent({ eventId: props.event_id, locales, timezone: props.default_timezone });
  const parentId = props.event_id ? null : new URLSearchParams(location.search).get('parent');
  const actions = useEventActions(ev, {
    calendarId: calendar.id,
    parentId,
    defaultLocale: locales[0] ?? 'en',
  });
  const preview = usePreview({
    times: times(ev.form),
    rrule: ev.form.rrule,
    eventId: props.event_id,
    calendarId: calendar.id,
  });
  const { event, form } = ev;
  const errors = actions.errors;
  const locked = Boolean(event?.locked && !event.can_publish);
  const readOnly = Boolean(event && (!event.can_write || locked));
  const isSub = Boolean(parentId ?? event?.parent_id);
  const hasSubs = (event?.sub_events.length ?? 0) > 0;
  const heading = t(event ? copy.title_edit : copy.title_new);
  const back = (
    <Button asChild variant="outline">
      <Link href={LIST}>{t(copy.back)}</Link>
    </Button>
  );
  const body =
    ev.state === 'loading' ? (
      <p role="status">{t(keys.events.common.loading)}</p>
    ) : ev.state === 'gone' ? (
      <p role="alert">{t(keys.events.errors.event_gone)}</p>
    ) : ev.state === 'error' ? (
      <div className="space-y-2">
        <p role="alert" className="text-destructive">
          {ev.loadError}
        </p>
        <Button variant="outline" onClick={() => void ev.load()}>
          {t(keys.events.common.retry)}
        </Button>
      </div>
    ) : (
      <div className="space-y-6">
        <p className="text-sm text-muted-foreground">{t(copy.calendar, { name: calendar.name })}</p>
        {readOnly && (
          <p role="status" className="rounded-md border bg-muted p-3 text-sm">
            {t(
              !event?.can_write
                ? copy.readonly_view
                : event.scheduled
                  ? copy.locked_scheduled
                  : copy.locked_published,
            )}
          </p>
        )}
        {actions.notice && (
          <p role="alert" className="text-destructive">
            {actions.notice}
          </p>
        )}
        <form
          ref={errors.formRef}
          noValidate
          className="grid gap-8"
          onSubmit={(e) => {
            e.preventDefault();
            void actions.save();
          }}
        >
          <TextsTabs
            locales={locales}
            defaultLocale={locales[0] ?? 'en'}
            texts={form.texts}
            tab={ev.tab}
            errors={errors.fields}
            disabled={readOnly}
            onTab={ev.setTab}
            onText={ev.setText}
            onEdit={errors.clearField}
          />
          <EventForm
            form={form}
            errors={errors.fields}
            disabled={readOnly}
            categories={props.categories}
            locales={locales}
            onChange={ev.setFields}
            onEdit={errors.clearField}
          />
          <RecurrenceEditor
            value={form.rrule}
            start={form.start}
            timezone={form.timezone}
            disabled={readOnly || isSub || hasSubs}
            reason={
              isSub
                ? t(keys.events.recurrence.disabled_sub_event)
                : hasSubs
                  ? t(keys.events.recurrence.disabled_has_sub_events)
                  : undefined
            }
            error={errors.fields.rrule}
            onChange={(rrule) => {
              ev.setFields({ rrule });
              errors.clearField('rrule');
            }}
          />
          {form.rrule.trim() && (
            <OccurrencesPreview
              occurrences={preview.occurrences}
              loading={preview.loading}
              error={preview.error}
              overrides={event?.overrides ?? []}
              allDay={form.all_day}
              timezone={form.timezone}
              saved={Boolean(event)}
              canOverride={Boolean(event) && !ev.dirty && !readOnly}
              busy={actions.busy}
              onSet={actions.setOverride}
              onClear={actions.clearOverride}
            />
          )}
          {errors.error && (
            <p role="alert" className="text-destructive">
              {errors.error}
            </p>
          )}
          {!readOnly && (
            <div>
              <Button disabled={actions.saving || Boolean(event && !ev.dirty)}>
                {t(
                  actions.saving
                    ? keys.events.common.saving
                    : event
                      ? keys.events.common.save
                      : copy.create,
                )}
              </Button>
            </div>
          )}
        </form>
        {event && (
          <SubEvents
            parentId={event.parent_id}
            subEvents={event.sub_events}
            calendarId={calendar.id}
            eventId={event.id}
            canAdd={!readOnly && !event.rrule && !event.parent_id}
          />
        )}
        <OrphanDialog
          orphans={actions.orphans}
          timezone={form.timezone}
          onConfirm={() => void actions.confirmOrphans()}
          onCancel={actions.cancelOrphans}
        />
      </div>
    );
  return (
    <>
      <Head title={heading} />
      <PageShell title={heading} actions={back}>
        {body}
      </PageShell>
    </>
  );
}
EventEditor.layout = [AuthenticatedLayout];
