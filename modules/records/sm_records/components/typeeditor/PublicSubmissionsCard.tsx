import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { keys, useT } from '../../utils/i18n';
import {
  defaultConfig,
  missingRequired,
  type PublicSubmissionsConfig,
  type SubmissionKind,
} from '../../utils/public-submissions';
import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { PublicFieldsChecklist } from './PublicFieldsChecklist';
import { PublicSubmissionsOptions } from './PublicSubmissionsOptions';
import type { EditableField } from './types';

const KINDS: SubmissionKind[] = ['form', 'subscription'];
const ENABLED_ID = 'public-submissions-enabled';
const KIND_ID = 'public-submissions-kind';

function Note({ tone, children }: { tone: 'warn' | 'error'; children: string }) {
  const color = tone === 'error' ? 'text-destructive' : 'text-amber-700 dark:text-amber-400';
  return (
    <p className={`text-sm ${color}`} role={tone === 'error' ? 'alert' : 'note'}>
      {children}
    </p>
  );
}

/**
 * "Accept submissions from the website" (#101): the type-editor card that
 * turns a record type into a contact form or a newsletter list, and
 * configures it.
 *
 * The switch is `enabled`. Turning it on for the first time also gives the
 * type its kind, which is chosen here and fixed once saved — the server
 * answers a change with a 409 (`public_submissions.config.check_change`), so
 * the select locks rather than offering it. Turning the switch off on a type
 * whose kind was never saved simply discards the draft config.
 *
 * Two warnings are advice, not refusals (design Q1): an empty `allowed_roles`
 * means anyone with `records.view` reads what visitors sent, and an empty
 * recipient list means nobody hears about it.
 */
export function PublicSubmissionsCard({
  isNew,
  savedKind,
  config,
  fields,
  allowedRoles,
  isPublic,
  contentLocales,
  errors,
  onChange,
  onPreset,
}: {
  isNew: boolean;
  /** The kind the server holds, or `null` — what locks the select. */
  savedKind: SubmissionKind | null;
  config: PublicSubmissionsConfig | null;
  fields: EditableField[];
  allowedRoles: string[];
  isPublic: boolean;
  contentLocales: string[];
  errors: ValidationError[];
  onChange: (next: PublicSubmissionsConfig | null) => void;
  /** *From a preset* — only offered while the type is new. */
  onPreset: (kind: SubmissionKind) => void;
}) {
  const { t } = useT();
  const ps = keys.records.public_submissions;
  const enabled = config?.enabled ?? false;
  const error = fieldMessage(errors, 'public_submissions');
  const kindLabel: Record<SubmissionKind, string> = {
    form: t(ps.kind_form),
    subscription: t(ps.kind_subscription),
  };
  const kindHelp: Record<SubmissionKind, string> = {
    form: t(ps.kind_form_help),
    subscription: t(ps.kind_subscription_help),
  };

  const toggle = (on: boolean) => {
    if (on) onChange({ ...(config ?? defaultConfig('form')), enabled: true });
    else if (config && savedKind === null) onChange(null);
    else if (config) onChange({ ...config, enabled: false });
  };
  const patch = (next: Partial<PublicSubmissionsConfig>) => {
    if (config) onChange({ ...config, ...next });
  };
  const missing = config ? missingRequired(fields, config.public_fields) : [];

  return (
    <Card data-testid="records-public-submissions">
      <CardHeader>
        <CardTitle>{t(ps.card_title)}</CardTitle>
        <CardDescription>{t(ps.card_help)}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        {isNew && savedKind === null && (
          <div className="grid gap-2" data-testid="records-public-submissions-presets">
            <p className="text-sm font-medium">{t(ps.preset_title)}</p>
            <div className="flex flex-wrap gap-2">
              {KINDS.map((kind) => (
                <Button key={kind} type="button" variant="outline" onClick={() => onPreset(kind)}>
                  {kindLabel[kind]}
                </Button>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">{t(ps.preset_help)}</p>
          </div>
        )}

        <div className="grid gap-1">
          <div className="flex items-center gap-2">
            <Switch
              id={ENABLED_ID}
              checked={enabled}
              onCheckedChange={(checked) => toggle(checked === true)}
            />
            <Label htmlFor={ENABLED_ID} className="font-normal">
              {t(ps.enabled)}
            </Label>
          </div>
          {config && <p className="text-sm text-muted-foreground">{t(ps.enabled_help)}</p>}
        </div>

        {config && isPublic && <Note tone="error">{t(ps.public_conflict)}</Note>}
        {config && allowedRoles.length === 0 && <Note tone="warn">{t(ps.roles_warning)}</Note>}

        {config && (
          <div className="grid gap-1.5">
            <Label htmlFor={KIND_ID}>{t(ps.kind)}</Label>
            <NativeSelect
              id={KIND_ID}
              value={config.kind}
              disabled={savedKind !== null}
              onChange={(e) =>
                onChange({ ...defaultConfig(e.target.value as SubmissionKind), enabled })
              }
            >
              {KINDS.map((kind) => (
                <NativeSelectOption key={kind} value={kind}>
                  {kindLabel[kind]}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <p className="text-sm text-muted-foreground">
              {savedKind !== null ? t(ps.kind_locked) : kindHelp[config.kind]}
            </p>
            {savedKind === null && !isNew && config.kind === 'subscription' && (
              <p className="text-sm text-muted-foreground">{t(ps.kind_new_only)}</p>
            )}
          </div>
        )}

        {config && (
          <PublicFieldsChecklist
            fields={fields}
            selected={config.public_fields}
            missing={enabled ? missing : []}
            onChange={(public_fields) => patch({ public_fields })}
          />
        )}

        {config && (
          <PublicSubmissionsOptions
            config={config}
            contentLocales={contentLocales}
            onChange={patch}
          />
        )}

        {error && <Note tone="error">{error}</Note>}
      </CardContent>
    </Card>
  );
}
