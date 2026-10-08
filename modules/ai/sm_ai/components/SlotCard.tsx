import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';

import type { SlotValues, TestResult } from '../utils/api';
import { keys, useT } from '../utils/i18n';

const OPENAI_COMPATIBLE = 'openai_compatible';

export function SlotCard({
  title,
  description,
  idPrefix,
  providers,
  optionalSlot,
  values,
  hasStoredKey,
  dirty,
  busy,
  testResult,
  onChange,
  onTest,
}: {
  title: string;
  description: string;
  idPrefix: string;
  providers: string[];
  /** Embedding-style slot: may be left unconfigured and carries a vector dim. */
  optionalSlot: boolean;
  values: SlotValues;
  hasStoredKey: boolean;
  /** Unsaved edits present — the probe would test the old saved settings. */
  dirty: boolean;
  busy: boolean;
  testResult: TestResult | null;
  onChange: (next: SlotValues) => void;
  onTest: () => void;
}) {
  const { t } = useT();
  const c = keys.ai.card;
  const set = (patch: Partial<SlotValues>) => onChange({ ...values, ...patch });
  const needsUrl = values.provider === OPENAI_COMPATIBLE;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-provider`}>{t(c.provider)}</Label>
          <select
            id={`${idPrefix}-provider`}
            className="border-input bg-background flex h-9 w-full rounded-md border px-3 py-1 text-sm"
            value={values.provider}
            onChange={(e) => set({ provider: e.target.value })}
            disabled={busy}
          >
            {optionalSlot && <option value="">{t(c.not_configured)}</option>}
            {/* An env-seeded value can fall outside the served list; without
                its own option the select would render unselected while every
                save 422s with no visible cause. Showing it makes the fix —
                re-picking a real provider — obvious. */}
            {values.provider !== '' && !providers.includes(values.provider) && (
              <option value={values.provider}>
                {t(c.unknown_provider, { provider: values.provider })}
              </option>
            )}
            {!optionalSlot && values.provider === '' && (
              <option value="">{t(c.pick_provider)}</option>
            )}
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-model`}>{t(c.model)}</Label>
          <Input
            id={`${idPrefix}-model`}
            value={values.model}
            onChange={(e) => set({ model: e.target.value })}
            placeholder={t(c.model_placeholder)}
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-url`}>
            {needsUrl ? t(c.base_url_required) : t(c.base_url_optional)}
          </Label>
          <Input
            id={`${idPrefix}-url`}
            value={values.base_url}
            onChange={(e) => set({ base_url: e.target.value })}
            placeholder={
              needsUrl ? t(c.base_url_placeholder_required) : t(c.base_url_placeholder_optional)
            }
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-key`}>{t(c.api_key)}</Label>
          <div className="flex gap-2">
            <Input
              id={`${idPrefix}-key`}
              type="password"
              value={values.api_key}
              onChange={(e) => set({ api_key: e.target.value, clear_key: false })}
              placeholder={hasStoredKey ? t(c.api_key_saved) : t(c.api_key_unset)}
              disabled={busy || values.clear_key}
            />
            {hasStoredKey && (
              <Button
                type="button"
                variant={values.clear_key ? 'destructive' : 'ghost'}
                size="sm"
                disabled={busy}
                onClick={() => set({ clear_key: !values.clear_key, api_key: '' })}
              >
                {values.clear_key ? t(c.will_clear) : t(c.clear)}
              </Button>
            )}
          </div>
        </div>
        {optionalSlot && (
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dim`}>{t(c.vector_dimension)}</Label>
            <Input
              id={`${idPrefix}-dim`}
              type="number"
              value={values.dim ?? 0}
              onChange={(e) => set({ dim: Number(e.target.value) || 0 })}
              disabled={busy}
            />
            <p className="text-xs text-muted-foreground">{t(c.vector_dimension_hint)}</p>
          </div>
        )}
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || dirty}
            onClick={onTest}
          >
            {t(c.test_connection)}
          </Button>
          {dirty && <span className="text-xs text-muted-foreground">{t(c.save_first)}</span>}
          {!dirty && testResult && (
            <span
              data-testid={`${idPrefix}-test-result`}
              className={testResult.ok ? 'text-sm text-emerald-600' : 'text-sm text-destructive'}
            >
              {testResult.ok
                ? t(c.test_ok, { model: testResult.model, latency: testResult.latency_ms })
                : testResult.error}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
