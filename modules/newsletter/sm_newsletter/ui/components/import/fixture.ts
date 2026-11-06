import type { ImportJob } from '../../utils/importTypes';

/** A staged two-column import of one subscribed file. */
export function stagedJob(over: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 7,
    list_type_key: 'news',
    status: 'staged',
    files: [{ name: 'subscribed.csv', kind: 'subscribed', rows: 12 }],
    columns: [
      { index: 0, header: 'Email Address' },
      { index: 1, header: 'First Name' },
    ],
    mapping: { fields: { '0': 'email' }, tags: false },
    targets: {
      fields: [
        { key: 'email', label: 'Email', type: 'email' },
        { key: 'first_name', label: 'First name', type: 'text' },
      ],
      tags: 'present',
    },
    tags_found: [{ label: 'VIP', value: 'vip', count: 3 }],
    total: 12,
    duplicates: 1,
    invalid: 2,
    processed: 0,
    created: 0,
    updated: 0,
    skipped: 0,
    suppressed: 0,
    failed: 0,
    errors: [],
    errors_total: 0,
    error_code: null,
    created_at: '2026-11-05T10:00:00Z',
    started_at: null,
    finished_at: null,
    ...over,
  };
}
