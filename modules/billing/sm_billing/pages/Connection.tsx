import { Head, router, usePage } from '@inertiajs/react';
import { CopyableId } from '@simple-module-py/ui/components/CopyableId';
import { InlineBanner } from '@simple-module-py/ui/components/InlineBanner';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { PasswordInput } from '@simple-module-py/ui/components/PasswordInput';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import { AlertTriangle, Info } from 'lucide-react';
import type React from 'react';
import { useState } from 'react';
import { toast } from 'sonner';
import { AdminNav } from '../components/AdminNav';
import { ADMIN_API, ApiError, api } from '../utils/api';
import { keys, translate, useT } from '../utils/i18n';
import type { AdminCommon, Connection as ConnectionInfo } from '../utils/types';

interface Props extends AdminCommon {
  connection: ConnectionInfo;
  webhook_url: string;
}

const RETURN_URL_MAX = 255;
const returnUrlRule = () => translate(keys.billing.connection.return_url_rule);

/** Mirrors the server's `normalise_return_url`: blank is fine, else an http(s) origin. */
function returnUrlError(raw: string): string {
  const value = raw.trim();
  if (!value) return '';
  if (value.length > RETURN_URL_MAX || /[\s?#@]/.test(value)) return returnUrlRule();
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return returnUrlRule();
  }
  const httpish = url.protocol === 'http:' || url.protocol === 'https:';
  return httpish && url.hostname && url.pathname === '/' ? '' : returnUrlRule();
}

function SecretField(props: {
  id: string;
  label: string;
  stored: boolean;
  value: string;
  clear: boolean;
  onValue: (v: string) => void;
  onClear: (v: boolean) => void;
}) {
  const { t } = useT();
  const c = keys.billing.connection;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={props.id}>{props.label}</Label>
      <PasswordInput
        id={props.id}
        autoComplete="off"
        showLabel={t(c.show)}
        hideLabel={t(c.hide)}
        placeholder={props.stored ? t(c.stored_placeholder) : t(c.not_set)}
        value={props.value}
        disabled={props.clear}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => props.onValue(e.target.value)}
      />
      {props.stored && (
        <Label className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
          <Checkbox checked={props.clear} onCheckedChange={(v) => props.onClear(v === true)} />
          {t(c.remove_stored)}
        </Label>
      )}
    </div>
  );
}

function Connection() {
  const { t } = useT();
  const c = keys.billing.connection;
  const { connection, webhook_url, csrf_token, can_manage } = usePage<{ props: Props }>()
    .props as unknown as Props;
  const [secret, setSecret] = useState('');
  const [webhook, setWebhook] = useState('');
  const [clearSecret, setClearSecret] = useState(false);
  const [clearWebhook, setClearWebhook] = useState(false);
  const [returnUrl, setReturnUrl] = useState(connection.return_base_url);
  const [returnUrlMsg, setReturnUrlMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const urlError = returnUrlError(returnUrl);
    setReturnUrlMsg(urlError);
    if (urlError) return;
    setBusy(true);
    try {
      await api(`${ADMIN_API}/connection`, csrf_token, {
        method: 'PUT',
        body: {
          stripe_secret_key: secret,
          stripe_webhook_secret: webhook,
          clear_secret_key: clearSecret,
          clear_webhook_secret: clearWebhook,
          return_base_url: returnUrl,
        },
      });
      toast.success(t(c.saved));
      setSecret('');
      setWebhook('');
      router.reload();
    } catch (err) {
      if (err instanceof ApiError && err.detail === 'invalid_return_url') {
        setReturnUrlMsg(String(err.body.message ?? returnUrlRule()));
        return;
      }
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stripeChosen = connection.provider === 'stripe';
  return (
    <>
      <Head title={t(c.head_title)} />
      <PageShell title={t(keys.billing.page.title)} description={t(c.description)}>
        <AdminNav active="connection" />
        <div className="max-w-2xl space-y-6">
          {connection.provider_error && (
            <InlineBanner
              icon={AlertTriangle}
              tone="warning"
              title={t(c.error_title)}
              description={t(c.error_description, { error: connection.provider_error })}
            />
          )}
          {!stripeChosen && (
            <InlineBanner
              icon={Info}
              title={t(c.manual_title)}
              description={t(c.manual_description)}
            />
          )}
          <Card>
            <CardHeader>
              <CardTitle>{t(c.webhook_title)}</CardTitle>
              <CardDescription>{t(c.webhook_description)}</CardDescription>
            </CardHeader>
            <CardContent>
              <CopyableId value={webhook_url} title={t(c.copy_webhook)} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t(c.secrets_title)}</CardTitle>
              <CardDescription>{t(c.secrets_description)}</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={save} className="space-y-4">
                <SecretField
                  id="stripe-secret"
                  label={t(c.secret_key)}
                  stored={connection.has_secret_key}
                  value={secret}
                  clear={clearSecret}
                  onValue={setSecret}
                  onClear={setClearSecret}
                />
                <SecretField
                  id="stripe-webhook"
                  label={t(c.webhook_secret)}
                  stored={connection.has_webhook_secret}
                  value={webhook}
                  clear={clearWebhook}
                  onValue={setWebhook}
                  onClear={setClearWebhook}
                />
                <div className="space-y-1.5">
                  <Label htmlFor="return-url">{t(c.return_url)}</Label>
                  <Input
                    id="return-url"
                    placeholder="https://app.example.com"
                    maxLength={RETURN_URL_MAX}
                    value={returnUrl}
                    aria-invalid={returnUrlMsg ? true : undefined}
                    aria-describedby={returnUrlMsg ? 'return-url-error' : undefined}
                    onChange={(e) => {
                      setReturnUrl(e.target.value);
                      setReturnUrlMsg('');
                    }}
                  />
                  {returnUrlMsg && (
                    <p id="return-url-error" role="alert" className="text-xs text-destructive">
                      {returnUrlMsg}
                    </p>
                  )}
                </div>
                {can_manage && (
                  <Button type="submit" disabled={busy}>
                    {t(c.save)}
                  </Button>
                )}
              </form>
            </CardContent>
          </Card>
        </div>
      </PageShell>
    </>
  );
}

Connection.layout = [AdminLayout];
export default Connection;
