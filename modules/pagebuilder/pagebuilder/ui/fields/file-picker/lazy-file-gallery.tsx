import {
  Component,
  type ComponentProps,
  type ComponentType,
  lazy,
  type ReactNode,
  Suspense,
  useState,
} from 'react';
import { keys, useT } from '../../utils/i18n';
import type { FileGallery as EagerGallery } from './file-gallery';

type Props = ComponentProps<typeof EagerGallery>;

// A new `lazy` per attempt: React caches a rejected import for the life of the component it made.
const load = () => lazy(() => import('./file-gallery').then((m) => ({ default: m.FileGallery })));

/** Catches the chunk that would not load (offline, or a deploy that replaced the hashed file), so
 *  the failure stays inside the picker and does not take the editor around it down. */
class ChunkBoundary extends Component<{ fallback: ReactNode; children: ReactNode }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function LoadFailed({ onRetry, onClose }: { onRetry: () => void; onClose: () => void }) {
  const { t } = useT();
  const button = 'rounded-md border px-3 py-1.5 text-sm hover:bg-muted';
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={t(keys.pagebuilder.gallery.title)}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-testid="gallery-load-failed"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      <div className="max-w-sm space-y-4 rounded-lg bg-background p-6 shadow-lg">
        <p className="text-sm">{t(keys.pagebuilder.gallery.chunk_failed)}</p>
        <div className="flex justify-end gap-2">
          {/* Focused on arrival, so Escape and Enter reach the notice, as they do the gallery. */}
          <button type="button" className={button} onClick={onClose} ref={(el) => el?.focus()}>
            {t(keys.pagebuilder.gallery.close)}
          </button>
          <button type="button" className={button} onClick={onRetry}>
            {t(keys.pagebuilder.gallery.retry)}
          </button>
        </div>
      </div>
    </div>
  );
}

function Loaded(props: Props) {
  const [attempt, setAttempt] = useState(0);
  const [Gallery, setGallery] = useState<ComponentType<Props>>(load);
  const retry = () => {
    setGallery(load);
    setAttempt((n) => n + 1);
  };
  return (
    <ChunkBoundary key={attempt} fallback={<LoadFailed onRetry={retry} onClose={props.onClose} />}>
      <Suspense fallback={null}>
        <Gallery {...props} />
      </Suspense>
    </ChunkBoundary>
  );
}

/** Keep the optional picker out of eagerly registered blocks' entry chunks. */
export function FileGallery(props: Props) {
  // Pickers stay mounted while closed; wait for an open before requesting the chunk.
  if (!props.open) return null;
  return <Loaded {...props} />;
}
