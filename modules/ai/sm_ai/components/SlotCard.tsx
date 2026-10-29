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

import { useId, useRef, useState } from 'react';

import {
  type ModelsResult,
  missingBaseUrl,
  needsBaseUrl,
  type SlotValues,
  type TestResult,
} from '../utils/api';
import { keys, useT } from '../utils/i18n';

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
  testing = false,
  testResult,
  onChange,
  onTest,
  onLoadModels,
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
  /** This slot's probe is in flight (it can take as long as the model does). */
  testing?: boolean;
  testResult: TestResult | null;
  onChange: (next: SlotValues) => void;
  onTest: () => void;
  /** Lists what the *saved* endpoint serves; failure is `ok: false`. */
  onLoadModels: () => Promise<ModelsResult>;
}) {
  const { t } = useT();
  const c = keys.ai.card;
  const needsUrl = needsBaseUrl(values);
  const urlMissing = missingBaseUrl(values);
  const listId = useId();
  const [models, setModels] = useState<ModelsResult | null>(null);
  const [loading, setLoading] = useState(false);
  // Bumped by every edit that invalidates a list, so a response still in
  // flight when the admin changes the endpoint is dropped, not shown.
  const request = useRef(0);
  // A list describes the endpoint it was fetched from, so editing the provider,
  // URL or key invalidates it. Typing in the model field must not: that is
  // what the suggestions are for.
  const set = (patch: Partial<SlotValues>) => {
    if (!('model' in patch) && !('dim' in patch)) {
      request.current += 1;
      setModels(null);
      // The dropped request no longer owns the button.
      setLoading(false);
    }
    onChange({ ...values, ...patch });
  };

  const loadModels = async () => {
    const mine = ++request.current;
    setLoading(true);
    try {
      const result = await onLoadModels();
      if (mine === request.current) setModels(result);
    } catch (err) {
      if (mine === request.current) {
        setModels({ ok: false, models: [], error: (err as Error).message });
      }
    } finally {
      if (mine === request.current) setLoading(false);
    }
  };

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
            {/* A value stored outside this page (set_setting.py, the Settings
                screen) can fall outside the served list; without
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
            // Suggestions, not a select: a model the server does not list (an
            // alias, a just-deployed one) must still be enterable.
            list={models?.ok ? listId : undefined}
          />
          {models?.ok && (
            <datalist id={listId}>
              {models.models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          )}
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
            required={needsUrl}
            aria-invalid={urlMissing}
            aria-describedby={urlMissing ? `${idPrefix}-url-error` : undefined}
          />
          {urlMissing && (
            <p id={`${idPrefix}-url-error`} className="text-xs text-destructive">
              {t(c.base_url_missing)}
            </p>
          )}
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
              min={0}
              value={values.dim ?? 0}
              onChange={(e) => set({ dim: Math.max(0, Math.trunc(Number(e.target.value)) || 0) })}
              disabled={busy}
            />
            <p className="text-xs text-muted-foreground">{t(c.vector_dimension_hint)}</p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || dirty}
            onClick={onTest}
            data-testid={`${idPrefix}-test-button`}
          >
            {testing ? t(c.testing) : t(c.test_connection)}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || dirty || loading}
            onClick={loadModels}
          >
            {t(c.load_models)}
          </Button>
          {dirty && <span className="text-xs text-muted-foreground">{t(c.save_first)}</span>}
          <span aria-live="polite">
            {testing && (
              <span
                data-testid={`${idPrefix}-test-pending`}
                className="text-sm text-muted-foreground"
              >
                {t(c.testing_hint)}
              </span>
            )}
            {!dirty && !testing && testResult && (
              <span
                data-testid={`${idPrefix}-test-result`}
                className={testResult.ok ? 'text-sm text-emerald-600' : 'text-sm text-destructive'}
              >
                {testResult.ok
                  ? t(c.test_ok, { model: testResult.model, latency: testResult.latency_ms })
                  : testResult.error}
              </span>
            )}
          </span>
        </div>
        {!dirty && models && (
          <p
            data-testid={`${idPrefix}-models-result`}
            className={models.ok ? 'text-xs text-muted-foreground' : 'text-sm text-destructive'}
          >
            {!models.ok
              ? models.error
              : models.models.length > 0
                ? t(models.truncated ? c.models_truncated : c.models_loaded, {
                    count: models.models.length,
                  })
                : t(c.models_none)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
