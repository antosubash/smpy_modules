// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';
import type { FieldDef } from '../../utils/types';

const { SubmissionDetails } = await import('./SubmissionDetails');
const { FieldRowSummary } = await import('../typeeditor/FieldRowSummary');

function def(key: string, type: string, system?: FieldDef['system']): FieldDef {
  return {
    key,
    type,
    label: `${key} label`,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...(system ? { system } : {}),
  };
}

describe('SubmissionDetails', () => {
  const fields = [
    def('name', 'text'),
    def('sm_source_page', 'text', 'readonly'),
    def('sm_ip_hash', 'text', 'readonly'),
    def('sm_nonce', 'text', 'internal'),
  ];

  it('shows readonly system values, folds the identifying ones, hides internal ones', async () => {
    const view = await mount(
      <SubmissionDetails
        fields={fields}
        data={{ name: 'Ada', sm_source_page: '/contact', sm_ip_hash: 'abc', sm_nonce: 'n' }}
      />,
    );
    const text = view.host.textContent ?? '';
    expect(text).toContain('Source page');
    expect(text).toContain('/contact');
    expect(view.find('details')?.textContent).toContain('abc');
    expect(text).not.toContain('Ada');
    expect(text).not.toContain('sm_nonce');
    await view.unmount();
  });

  it('renders nothing for an ordinary type or a new record', async () => {
    const view = await mount(<SubmissionDetails fields={[def('name', 'text')]} data={{}} />);
    expect(view.find('[data-testid="records-submission-details"]')).toBeNull();
    await view.render(<SubmissionDetails fields={fields} data={null} />);
    expect(view.find('[data-testid="records-submission-details"]')).toBeNull();
    await view.unmount();
  });
});

describe('FieldRowSummary — a system field is locked', () => {
  it('shows a System badge and offers no controls', async () => {
    const field = { ...def('sm_spam', 'select', 'readonly'), uid: 'x', fromServer: true };
    const onToggle = vi.fn();
    const view = await mount(
      <FieldRowSummary
        field={field}
        index={0}
        total={1}
        expanded={false}
        disabled={false}
        invalid={false}
        moveUpRef={null}
        moveDownRef={null}
        onToggle={onToggle}
        onRemove={vi.fn()}
        onMoveUp={vi.fn()}
        onMoveDown={vi.fn()}
      />,
    );
    expect(view.find('[data-testid="records-field-system"]')?.textContent).toBe('System');
    expect(view.find<HTMLButtonElement>('[data-testid="records-field-toggle"]')?.disabled).toBe(
      true,
    );
    expect(view.find('[aria-label="Remove field"]')?.closest('.hidden')).not.toBeNull();
    await view.unmount();
  });
});
