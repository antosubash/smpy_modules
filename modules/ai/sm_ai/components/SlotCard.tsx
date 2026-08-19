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

const OPENAI_COMPATIBLE = 'openai_compatible';

export function SlotCard({
  title,
  description,
  idPrefix,
  providers,
  allowEmptyProvider,
  values,
  hasStoredKey,
  showDim,
  busy,
  testResult,
  onChange,
  onTest,
}: {
  title: string;
  description: string;
  idPrefix: string;
  providers: string[];
  allowEmptyProvider: boolean;
  values: SlotValues;
  hasStoredKey: boolean;
  showDim: boolean;
  busy: boolean;
  testResult: TestResult | null;
  onChange: (next: SlotValues) => void;
  onTest: () => void;
}) {
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
          <Label htmlFor={`${idPrefix}-provider`}>Provider</Label>
          <select
            id={`${idPrefix}-provider`}
            className="border-input bg-background flex h-9 w-full rounded-md border px-3 py-1 text-sm"
            value={values.provider}
            onChange={(e) => set({ provider: e.target.value })}
            disabled={busy}
          >
            {allowEmptyProvider && <option value="">Not configured</option>}
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-model`}>Model</Label>
          <Input
            id={`${idPrefix}-model`}
            value={values.model}
            onChange={(e) => set({ model: e.target.value })}
            placeholder="model name, no provider prefix"
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-url`}>
            Base URL{needsUrl ? ' (required)' : ' (optional override)'}
          </Label>
          <Input
            id={`${idPrefix}-url`}
            value={values.base_url}
            onChange={(e) => set({ base_url: e.target.value })}
            placeholder={needsUrl ? 'http://your-server:8000/v1' : 'provider default'}
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-key`}>API key</Label>
          <div className="flex gap-2">
            <Input
              id={`${idPrefix}-key`}
              type="password"
              value={values.api_key}
              onChange={(e) => set({ api_key: e.target.value, clear_key: false })}
              placeholder={hasStoredKey ? 'saved — leave blank to keep' : 'not set'}
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
                {values.clear_key ? 'Will clear' : 'Clear'}
              </Button>
            )}
          </div>
        </div>
        {showDim && (
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dim`}>Vector dimension</Label>
            <Input
              id={`${idPrefix}-dim`}
              type="number"
              value={values.dim ?? 0}
              onChange={(e) => set({ dim: Number(e.target.value) || 0 })}
              disabled={busy}
            />
            <p className="text-xs text-muted-foreground">
              Vector stores fix collection width to this — changing it means re-indexing.
            </p>
          </div>
        )}
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onTest}>
            Test connection
          </Button>
          {testResult && (
            <span
              data-testid={`${idPrefix}-test-result`}
              className={testResult.ok ? 'text-sm text-emerald-600' : 'text-sm text-destructive'}
            >
              {testResult.ok
                ? `OK — ${testResult.model} (${testResult.latency_ms} ms)`
                : testResult.error}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
