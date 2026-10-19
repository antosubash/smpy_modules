import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../locales/en.json';
import { uploadMedia } from '../utils/api';
import { useMediaUploads } from './useMediaUploads';

// The vitest environment is `node` with no React renderer, so the hook runs
// against a stubbed `react`: state setters are no-ops and callbacks are
// returned as-is. That is enough to drive `startUploads` and observe its
// side effects (toasts, upload calls), which is what this guards.
vi.mock('react', () => ({
  useState: (initial: unknown) => [initial, vi.fn()],
  useCallback: (fn: unknown) => fn,
}));
vi.mock('@inertiajs/react', () => ({ router: { reload: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));
vi.mock('../utils/api', () => ({ uploadMedia: vi.fn() }));

const file = (name: string) => new File(['x'], name, { type: 'image/png' });
const flush = () => new Promise((r) => setTimeout(r, 0));

function start(files: File[]) {
  // biome-ignore lint/correctness/useHookAtTopLevel: react is stubbed; the hook is plain code here
  const uploads = useMediaUploads({
    uploadFolder: '',
    onUploaded: vi.fn(),
    setMessage: vi.fn(),
  });
  uploads.startUploads(files);
  return flush();
}

describe('useMediaUploads failure reporting', () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    vi.mocked(uploadMedia).mockReset();
  });

  it('raises one toast with the translated message for a rejected file', async () => {
    vi.mocked(uploadMedia).mockRejectedValue(new Error(en.errors.upload_unsupported));
    await start([file('bad.png')]);
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      `Could not upload bad.png: ${en.errors.upload_unsupported}`,
    );
  });

  it('summarises several failures in a single toast', async () => {
    vi.mocked(uploadMedia).mockRejectedValue(new Error('nope'));
    await start([file('a.png'), file('b.png'), file('c.png')]);
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith('3 files could not be uploaded.');
  });

  it('raises no toast when every upload succeeds', async () => {
    vi.mocked(uploadMedia).mockResolvedValue({} as never);
    await start([file('a.png')]);
    expect(toast.error).not.toHaveBeenCalled();
  });
});
