import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { SlotCard } from '../components/SlotCard';
import {
  type AiSettingsOut,
  loadSettings,
  type SlotValues,
  saveSettings,
  type TestResult,
  testSlot,
} from '../utils/api';
import { keys, useT } from '../utils/i18n';

const emptySlot = (): SlotValues => ({
  provider: '',
  model: '',
  base_url: '',
  api_key: '',
  clear_key: false,
});

function fromSettings(s: AiSettingsOut): { chat: SlotValues; embedding: SlotValues } {
  return {
    chat: {
      provider: s.chat_provider,
      model: s.chat_model,
      base_url: s.chat_base_url,
      api_key: '',
      clear_key: false,
    },
    embedding: {
      provider: s.embedding_provider,
      model: s.embedding_model,
      base_url: s.embedding_base_url,
      api_key: '',
      clear_key: false,
      dim: s.embedding_dim,
    },
  };
}

function Settings() {
  const { t } = useT();
  const [loaded, setLoaded] = useState<AiSettingsOut | null>(null);
  const [chat, setChat] = useState<SlotValues>(emptySlot());
  const [embedding, setEmbedding] = useState<SlotValues>(emptySlot());
  const [busy, setBusy] = useState(false);
  const [chatTest, setChatTest] = useState<TestResult | null>(null);
  const [embeddingTest, setEmbeddingTest] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // One hydration path for both the initial load and the post-save read-back,
  // so the editable state cannot drift from `loaded` in just one of them.
  const hydrate = useCallback((s: AiSettingsOut) => {
    setLoaded(s);
    const slots = fromSettings(s);
    setChat(slots.chat);
    setEmbedding(slots.embedding);
  }, []);

  useEffect(() => {
    loadSettings()
      .then(hydrate)
      .catch((err) => setError((err as Error).message));
  }, [hydrate]);

  async function run(work: () => Promise<void>, errorMsg: string) {
    setBusy(true);
    try {
      await work();
    } catch (err) {
      toast.error(
        t(keys.ai.settings.error_with_reason, {
          message: errorMsg,
          reason: (err as Error).message,
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    run(async () => {
      hydrate(await saveSettings(chat, embedding));
      // Results describe the previous configuration — drop them.
      setChatTest(null);
      setEmbeddingTest(null);
      toast.success(t(keys.ai.settings.saved));
    }, t(keys.ai.settings.save_failed));

  // The probe runs against *saved* settings; testing with unsaved edits
  // would report on the old configuration and mislead either way.
  // Field-by-field, not JSON.stringify: serialized equality is key-order and
  // missing-vs-undefined sensitive (chat slots carry no `dim`), so equal
  // states could compare unequal and disable Test with no visible reason.
  const isDirty = (slot: SlotValues, saved: SlotValues) =>
    slot.provider !== saved.provider ||
    slot.model !== saved.model ||
    slot.base_url !== saved.base_url ||
    slot.api_key !== '' ||
    slot.clear_key ||
    (slot.dim ?? 0) !== (saved.dim ?? 0);
  const savedSlots = useMemo(() => (loaded ? fromSettings(loaded) : null), [loaded]);

  const test = (slot: 'chat' | 'embedding') =>
    run(async () => {
      const result = await testSlot(slot);
      (slot === 'chat' ? setChatTest : setEmbeddingTest)(result);
    }, t(keys.ai.settings.test_failed));

  return (
    <>
      <Head title={t(keys.ai.settings.head_title)} />
      <PageShell title={t(keys.ai.settings.title)} description={t(keys.ai.settings.description)}>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!loaded && !error && (
          <p className="text-sm text-muted-foreground">{t(keys.ai.settings.loading)}</p>
        )}
        {loaded && savedSlots && (
          <div className="space-y-6">
            <SlotCard
              title={t(keys.ai.slots.chat_title)}
              description={t(keys.ai.slots.chat_description)}
              idPrefix="ai-chat"
              providers={loaded.chat_providers}
              optionalSlot={false}
              values={chat}
              hasStoredKey={loaded.has_chat_api_key}
              dirty={isDirty(chat, savedSlots.chat)}
              busy={busy}
              testResult={chatTest}
              onChange={setChat}
              onTest={() => test('chat')}
            />
            <SlotCard
              title={t(keys.ai.slots.embedding_title)}
              description={t(keys.ai.slots.embedding_description)}
              idPrefix="ai-embedding"
              providers={loaded.embedding_providers}
              optionalSlot={true}
              values={embedding}
              hasStoredKey={loaded.has_embedding_api_key}
              dirty={isDirty(embedding, savedSlots.embedding)}
              busy={busy}
              testResult={embeddingTest}
              onChange={setEmbedding}
              onTest={() => test('embedding')}
            />
            <Button type="button" disabled={busy} onClick={save}>
              {t(keys.ai.settings.save)}
            </Button>
          </div>
        )}
      </PageShell>
    </>
  );
}

Settings.layout = [AuthenticatedLayout];
export default Settings;
