/** What the Import screen's tests share: an import as the API returns it, and its items. */
export const IMPORTS = '/api/events/imports';

export function importOut(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    calendar: { id: 'c1', name: 'Team' },
    status: 'staged',
    filename: 'cal.ics',
    size_bytes: 1200,
    total: 3,
    counts: { new: 2, update: 1, skip: 0 },
    reasons: {},
    dropped: {},
    created: 0,
    updated: 0,
    unchanged: 0,
    skipped: 0,
    failed: 0,
    processed: 0,
    error_code: null,
    publish: false,
    created_at: '2026-11-18T10:00:00Z',
    finished_at: null,
    ...over,
  };
}

export function item(seq: number, over: Record<string, unknown> = {}) {
  return {
    seq,
    uid: `u${seq}@x`,
    verdict: 'new',
    reason: null,
    notes: [],
    title: `Talk ${seq}`,
    starts_at: '2026-07-01T08:00:00Z',
    timezone: 'Europe/Vienna',
    local_start: '2026-07-01T10:00',
    all_day: false,
    recurring: false,
    outcome: null,
    outcome_code: null,
    event_id: null,
    ...over,
  };
}

export const page = (items: unknown[], total = items.length) => ({
  items,
  total,
  page: 1,
  page_size: 50,
});

export const baseProps = {
  calendars: [
    { id: 'c1', name: 'Team', color: '#2563eb', default_timezone: 'Europe/Vienna' },
    { id: 'c2', name: 'Office', color: '#16a34a', default_timezone: 'UTC' },
  ],
  can_publish: false,
  max_bytes: 5 * 1024 * 1024,
  import_id: null as number | null,
};

export function icsFile(size?: number): File {
  const file = new File(['BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'], 'cal.ics', {
    type: 'text/calendar',
  });
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size });
  return file;
}

/** Put a file into an `<input type="file">` the way a browser does. */
export async function choose(input: HTMLInputElement, file: File) {
  const { act } = await import('./test-dom');
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
