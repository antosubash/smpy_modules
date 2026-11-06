import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useRef, useState } from 'react';

import { LiftDialog } from '../ui/components/suppressions/LiftDialog';
import { LiftLog } from '../ui/components/suppressions/LiftLog';
import { REASON_LABELS } from '../ui/components/suppressions/labels';
import { SuppressionTable } from '../ui/components/suppressions/SuppressionTable';
import { PAGE_SIZE, useSuppressionList } from '../ui/hooks/useSuppressionList';
import { api, errorMessage } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import type { Suppression, SuppressionReason } from '../ui/utils/types';

const copy = keys.newsletter.suppressions;
const REASONS = Object.keys(REASON_LABELS) as SuppressionReason[];

type Tab = 'active' | 'lifted';

/** Suppressed addresses, a lookup by email and the audited lifts. Needs `newsletter.manage`. */
export default function Suppressions() {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const list = useSuppressionList();
  const [tab, setTab] = useState<Tab>('active');
  const [typed, setTyped] = useState('');
  const [lookup, setLookup] = useState<{ email: string; items: Suppression[] } | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lifting, setLifting] = useState<Suppression | null>(null);

  const runLookup = async () => {
    const email = typed.trim();
    if (!email) return;
    setLookupError(null);
    try {
      setLookup({ email, items: await api.lookupSuppressions(email) });
    } catch (e) {
      setLookupError(errorMessage(e, tRef.current));
    }
  };
  const clearLookup = () => {
    setLookup(null);
    setLookupError(null);
    setTyped('');
  };
  const refresh = () => {
    list.reload();
    if (lookup)
      void api.lookupSuppressions(lookup.email).then((items) => setLookup({ ...lookup, items }));
  };

  const shown = lookup ? lookup.items : list.items;
  const error = lookupError ?? list.error;
  const total = list.total;

  return (
    <PageShell title={t(copy.title)} description={t(copy.description)}>
      <Head title={t(copy.title)} />
      <div className="mb-4 flex gap-2">
        {(['active', 'lifted'] as const).map((id) => (
          <Button
            key={id}
            size="sm"
            variant={tab === id ? 'default' : 'outline'}
            aria-pressed={tab === id}
            onClick={() => setTab(id)}
          >
            {t(id === 'active' ? copy.tab_active : copy.tab_lifted)}
          </Button>
        ))}
      </div>

      {tab === 'lifted' ? (
        <LiftLog />
      ) : (
        <>
          {error && (
            <p role="alert" className="mb-4 text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="mb-4 flex flex-wrap items-end gap-4">
            <div className="grid gap-1">
              <Label htmlFor="newsletter-suppressions-reason">{t(copy.reason_label)}</Label>
              <NativeSelect
                id="newsletter-suppressions-reason"
                value={list.reason}
                disabled={lookup !== null}
                onChange={(e) => list.setReason(e.target.value)}
              >
                <option value="">{t(copy.reason_all)}</option>
                {REASONS.map((r) => (
                  <option key={r} value={r}>
                    {`${t(REASON_LABELS[r])} (${list.counts[r] ?? 0})`}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void runLookup();
              }}
            >
              <div className="grid gap-1">
                <Label htmlFor="newsletter-suppressions-lookup">{t(copy.lookup_label)}</Label>
                <Input
                  id="newsletter-suppressions-lookup"
                  type="email"
                  autoComplete="off"
                  value={typed}
                  maxLength={320}
                  onChange={(e) => setTyped(e.target.value)}
                />
              </div>
              <Button type="submit" disabled={typed.trim() === ''}>
                {t(copy.lookup_submit)}
              </Button>
              {lookup && (
                <Button type="button" variant="outline" onClick={clearLookup}>
                  {t(copy.lookup_clear)}
                </Button>
              )}
            </form>
          </div>

          {shown !== null && shown.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="font-medium">{t(copy.empty)}</p>
            </div>
          ) : (
            shown !== null && <SuppressionTable items={shown} onLift={setLifting} />
          )}

          {!lookup && shown !== null && shown.length > 0 && (
            <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {t(keys.newsletter.campaigns.showing, {
                  from: list.offset + 1,
                  to: list.offset + shown.length,
                  total,
                })}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={list.offset === 0}
                  onClick={() => list.setOffset(Math.max(0, list.offset - PAGE_SIZE))}
                >
                  {t(keys.newsletter.campaigns.previous)}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={list.offset + PAGE_SIZE >= total}
                  onClick={() => list.setOffset(list.offset + PAGE_SIZE)}
                >
                  {t(keys.newsletter.campaigns.next)}
                </Button>
              </div>
            </div>
          )}

          {lifting && (
            <LiftDialog
              suppression={lifting}
              knownEmail={lookup?.email}
              open
              onOpenChange={(o) => !o && setLifting(null)}
              onLifted={refresh}
              onStale={refresh}
            />
          )}
        </>
      )}
    </PageShell>
  );
}

Suppressions.layout = [AuthenticatedLayout];
