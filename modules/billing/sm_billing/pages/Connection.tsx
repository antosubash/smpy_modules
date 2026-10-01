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
import { ADMIN_API, api } from '../utils/api';
import type { AdminCommon, Connection as ConnectionInfo } from '../utils/types';

interface Props extends AdminCommon {
  connection: ConnectionInfo;
  webhook_url: string;
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
  return (
    <div className="space-y-1.5">
      <Label htmlFor={props.id}>{props.label}</Label>
      <PasswordInput
        id={props.id}
        autoComplete="off"
        showLabel="Show"
        hideLabel="Hide"
        placeholder={props.stored ? 'Stored — leave blank to keep' : 'Not set'}
        value={props.value}
        disabled={props.clear}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => props.onValue(e.target.value)}
      />
      {props.stored && (
        <Label className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
          <Checkbox checked={props.clear} onCheckedChange={(v) => props.onClear(v === true)} />
          Remove the stored value
        </Label>
      )}
    </div>
  );
}

function Connection() {
  const { connection, webhook_url, csrf_token, can_manage } = usePage<{ props: Props }>()
    .props as unknown as Props;
  const [secret, setSecret] = useState('');
  const [webhook, setWebhook] = useState('');
  const [clearSecret, setClearSecret] = useState(false);
  const [clearWebhook, setClearWebhook] = useState(false);
  const [returnUrl, setReturnUrl] = useState(connection.return_base_url);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
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
      toast.success('Stripe connection saved');
      setSecret('');
      setWebhook('');
      router.reload();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stripeChosen = connection.provider === 'stripe';
  return (
    <>
      <Head title="Stripe connection" />
      <PageShell title="Billing" description="How this site talks to Stripe.">
        <AdminNav active="connection" />
        <div className="max-w-2xl space-y-6">
          {connection.provider_error && (
            <InlineBanner
              icon={AlertTriangle}
              tone="warning"
              title="Stripe is configured but not in use"
              description={`${connection.provider_error}. Billing runs on the manual provider until this is fixed.`}
            />
          )}
          {!stripeChosen && (
            <InlineBanner
              icon={Info}
              title="The manual provider is active"
              description="Set the billing provider to 'stripe' on the Settings screen and restart to take payments."
            />
          )}
          <Card>
            <CardHeader>
              <CardTitle>Webhook endpoint</CardTitle>
              <CardDescription>
                Add this URL in Stripe → Developers → Webhooks, with the events
                checkout.session.completed and customer.subscription.*.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CopyableId value={webhook_url} label="Webhook URL" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Secrets</CardTitle>
              <CardDescription>Stored encrypted with the app&apos;s secret key.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={save} className="space-y-4">
                <SecretField
                  id="stripe-secret"
                  label="Secret key (sk_…)"
                  stored={connection.has_secret_key}
                  value={secret}
                  clear={clearSecret}
                  onValue={setSecret}
                  onClear={setClearSecret}
                />
                <SecretField
                  id="stripe-webhook"
                  label="Webhook signing secret (whsec_…)"
                  stored={connection.has_webhook_secret}
                  value={webhook}
                  clear={clearWebhook}
                  onValue={setWebhook}
                  onClear={setClearWebhook}
                />
                <div className="space-y-1.5">
                  <Label htmlFor="return-url">Return URL origin</Label>
                  <Input
                    id="return-url"
                    placeholder="https://app.example.com"
                    value={returnUrl}
                    onChange={(e) => setReturnUrl(e.target.value)}
                  />
                </div>
                {can_manage && (
                  <Button type="submit" disabled={busy}>
                    Save connection
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
