import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect, useState } from 'react';
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

export default function Settings() {
  const [loaded, setLoaded] = useState<AiSettingsOut | null>(null);
  const [chat, setChat] = useState<SlotValues>(emptySlot());
  const [embedding, setEmbedding] = useState<SlotValues>(emptySlot());
  const [busy, setBusy] = useState(false);
  const [chatTest, setChatTest] = useState<TestResult | null>(null);
  const [embeddingTest, setEmbeddingTest] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSettings()
      .then((s) => {
        setLoaded(s);
        const slots = fromSettings(s);
        setChat(slots.chat);
        setEmbedding(slots.embedding);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  async function run(work: () => Promise<void>, errorMsg: string) {
    setBusy(true);
    try {
      await work();
    } catch (err) {
      toast.error(`${errorMsg}: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    run(async () => {
      const next = await saveSettings(chat, embedding);
      setLoaded(next);
      const slots = fromSettings(next);
      setChat(slots.chat);
      setEmbedding(slots.embedding);
      // Results describe the previous configuration — drop them.
      setChatTest(null);
      setEmbeddingTest(null);
      toast.success('AI settings saved');
    }, 'Save failed');

  // The probe runs against *saved* settings; testing with unsaved edits
  // would report on the old configuration and mislead either way.
  const isDirty = (slot: SlotValues, saved: SlotValues) =>
    JSON.stringify(slot) !== JSON.stringify(saved);
  const savedSlots = loaded ? fromSettings(loaded) : null;

  const test = (slot: 'chat' | 'embedding') =>
    run(async () => {
      const result = await testSlot(slot);
      (slot === 'chat' ? setChatTest : setEmbeddingTest)(result);
    }, 'Test failed');

  return (
    <AuthenticatedLayout>
      <Head title="AI Settings" />
      <PageShell
        title="AI"
        description="Connection settings for the chat and embedding providers every module shares."
      >
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!loaded && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
        {loaded && savedSlots && (
          <div className="space-y-6">
            <SlotCard
              title="Chat"
              description="The model modules use for text generation."
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
              title="Embeddings"
              description="Optional second endpoint for vector embeddings."
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
              Save
            </Button>
          </div>
        )}
      </PageShell>
    </AuthenticatedLayout>
  );
}
