// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpError } from '../utils/http';
import * as importApi from '../utils/importApi';
import type { ImportJob } from '../utils/importTypes';
import { IMPORT_POLL_MS, useImport } from './useImport';

vi.mock('../utils/importApi', () => ({
  uploadImport: vi.fn(),
  getImport: vi.fn(),
  setMapping: vi.fn(),
  applyImport: vi.fn(),
  discardImport: vi.fn(),
}));
vi.mock('../utils/http', () => ({
  errorMessage: (e: { code?: string }) => `shown ${e.code}`,
  HttpError: class HttpError extends Error {
    status: number;
    code: string | null;
    constructor(message: string, status: number, code: string | null = null) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const job = (status: ImportJob['status']): ImportJob =>
  ({ id: 4, status, list_type_key: 'news', processed: 0, total: 5 }) as ImportJob;

let initial: number | null;
let result: ReturnType<typeof useImport>;
function Harness() {
  result = useImport(initial);
  return null;
}

describe('useImport', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(importApi.getImport).mockReset().mockResolvedValue(job('queued'));
    vi.mocked(importApi.uploadImport).mockReset();
    initial = null;
  });
  afterEach(() => vi.useRealTimers());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
    return root;
  }
  const tick = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  it('polls while queued and stops once done', async () => {
    initial = 4;
    await mount();
    expect(importApi.getImport).toHaveBeenCalledTimes(1);
    await tick(IMPORT_POLL_MS);
    expect(importApi.getImport).toHaveBeenCalledTimes(2);
    vi.mocked(importApi.getImport).mockResolvedValue(job('done'));
    await tick(IMPORT_POLL_MS);
    expect(importApi.getImport).toHaveBeenCalledTimes(3);
    expect(result.job?.status).toBe('done');
    await tick(IMPORT_POLL_MS * 3);
    expect(importApi.getImport).toHaveBeenCalledTimes(3);
  });

  it('returns to the start when polling gets a 404', async () => {
    initial = 4;
    await mount();
    expect(result.job?.status).toBe('queued');
    vi.mocked(importApi.getImport).mockRejectedValue(new HttpError('gone', 404, 'not_found'));
    await tick(IMPORT_POLL_MS);
    expect(result.job).toBeNull();
    await tick(IMPORT_POLL_MS * 3);
    expect(importApi.getImport).toHaveBeenCalledTimes(2);
  });

  it('does not poll a staged job', async () => {
    vi.mocked(importApi.getImport).mockResolvedValue(job('staged'));
    initial = 4;
    await mount();
    await tick(IMPORT_POLL_MS * 3);
    expect(importApi.getImport).toHaveBeenCalledTimes(1);
  });

  it('aborts the request in flight on unmount', async () => {
    initial = 4;
    let signal: AbortSignal | undefined;
    vi.mocked(importApi.getImport).mockImplementation((_id, s) => {
      signal = s;
      return new Promise(() => undefined);
    });
    const root = await mount();
    expect(signal?.aborted).toBe(false);
    await act(async () => root.unmount());
    expect(signal?.aborted).toBe(true);
  });

  it('shows the translated message when an upload fails', async () => {
    vi.mocked(importApi.uploadImport).mockRejectedValue({ code: 'import_not_utf8' });
    await mount();
    await act(async () => result.upload('news', []));
    expect(result.error).toBe('shown import_not_utf8');
    expect(result.job).toBeNull();
    expect(result.busy).toBe(false);
  });

  it('adopts the uploaded job and starts polling after apply', async () => {
    vi.mocked(importApi.uploadImport).mockResolvedValue(job('staged'));
    vi.mocked(importApi.applyImport).mockResolvedValue(job('queued'));
    await mount();
    await act(async () => result.upload('news', []));
    expect(result.job?.status).toBe('staged');
    await act(async () => result.apply());
    expect(result.job?.status).toBe('queued');
    await tick(IMPORT_POLL_MS);
    expect(importApi.getImport).toHaveBeenCalledTimes(1);
  });

  it('stops polling on a 4xx refusal but keeps retrying a 5xx', async () => {
    initial = 4;
    await mount();
    vi.mocked(importApi.getImport).mockRejectedValue(new HttpError('x', 503));
    await tick(IMPORT_POLL_MS * 2);
    expect(importApi.getImport).toHaveBeenCalledTimes(3);
    vi.mocked(importApi.getImport).mockRejectedValue(new HttpError('x', 404, 'not_found'));
    await tick(IMPORT_POLL_MS);
    expect(importApi.getImport).toHaveBeenCalledTimes(4);
    await tick(IMPORT_POLL_MS * 3);
    expect(importApi.getImport).toHaveBeenCalledTimes(4);
    expect(result.error).toBe('shown not_found');
  });

  it('lets only the latest request set the job and clear busy', async () => {
    await mount();
    const pending: Array<(j: ImportJob) => void> = [];
    vi.mocked(importApi.getImport).mockImplementation(
      () => new Promise<ImportJob>((resolve) => pending.push(resolve)),
    );
    await act(async () => result.open(1));
    await act(async () => result.open(2));
    await act(async () => pending[1]({ ...job('staged'), id: 2 }));
    expect(result.job?.id).toBe(2);
    expect(result.busy).toBe(false);
    await act(async () => pending[0]({ ...job('staged'), id: 1 }));
    expect(result.job?.id).toBe(2);
  });
});
