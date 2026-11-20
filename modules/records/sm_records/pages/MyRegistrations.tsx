import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useState } from 'react';
import { RecordsLayout } from '../ui/components/RecordsLayout';
import { keys, useT } from '../ui/utils/i18n';
import { cancelMine, listMine, type Mine } from '../ui/utils/my-registrations-api';

type State = { kind: 'loading' } | { kind: 'error' } | ({ kind: 'ready' } & Mine);

/** `Records/MyRegistrations`: the signed-in person's own upcoming registrations, from the server's
 *  list for their verified address. An unverified address sees why, never a list. Cancelling asks
 *  once, then frees the seat. */
function MyRegistrations() {
  const { t } = useT();
  const copy = keys.records.events.mine;
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [asking, setAsking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      setState({ kind: 'ready', ...(await listMine()) });
    } catch {
      setState({ kind: 'error' });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function cancel(uuid: string) {
    setBusy(true);
    try {
      setState({ kind: 'ready', ...(await cancelMine(uuid)) });
      setNotice({ ok: true, text: t(copy.cancelled) });
    } catch {
      setNotice({ ok: false, text: t(copy.cancel_failed) });
    } finally {
      setAsking(null);
      setBusy(false);
    }
  }

  let body: React.ReactNode;
  if (state.kind === 'loading') {
    body = <p role="status">{t(copy.loading)}</p>;
  } else if (state.kind === 'error') {
    body = (
      <p role="alert">
        {t(copy.load_failed)}{' '}
        <button type="button" className="underline" onClick={() => void load()}>
          {t(copy.retry)}
        </button>
      </p>
    );
  } else if (!state.verified) {
    body = (
      <p role="status" data-testid="mine-unverified">
        {t(copy.unverified)}
      </p>
    );
  } else if (state.items.length === 0) {
    body = <p data-testid="mine-empty">{t(copy.empty)}</p>;
  } else {
    body = (
      <ul className="space-y-3" data-testid="mine-list">
        {state.items.map((item) => (
          <li key={item.uuid} className="rounded-md border p-4" data-testid="mine-item">
            <p className="font-medium">
              {item.page_path ? <a href={item.page_path}>{item.title}</a> : item.title}
            </p>
            {item.when_text ? <p className="text-sm">{item.when_text}</p> : null}
            <p className="text-sm text-muted-foreground">
              {t(item.status === 'pending' ? copy.pending : copy.registered)}
            </p>
            {asking === item.uuid ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-sm">{t(copy.cancel_confirm)}</span>
                <Button disabled={busy} onClick={() => void cancel(item.uuid)}>
                  {t(copy.cancel_yes)}
                </Button>
                <Button variant="outline" disabled={busy} onClick={() => setAsking(null)}>
                  {t(copy.cancel_no)}
                </Button>
              </div>
            ) : (
              <Button variant="outline" className="mt-2" onClick={() => setAsking(item.uuid)}>
                {t(copy.cancel)}
              </Button>
            )}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell title={t(copy.title)}>
        <p className="mb-4 text-sm text-muted-foreground">{t(copy.intro)}</p>
        {notice ? (
          <p role={notice.ok ? 'status' : 'alert'} className="mb-4">
            {notice.text}
          </p>
        ) : null}
        {body}
      </PageShell>
    </>
  );
}

MyRegistrations.layout = [RecordsLayout];
export default MyRegistrations;
