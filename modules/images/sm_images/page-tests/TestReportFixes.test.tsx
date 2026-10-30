// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount, setValue } from '../test-dom';
import type { PipelineOverview } from '../utils/types';
import { flush, job, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { toast } = await import('sonner');
const { PipelineTab, changed } = await import('../components/pipeline/PipelineTab');
const { ImportsTab } = await import('../components/imports/ImportsTab');
const { CreateCollectionDialog } = await import(
  '../components/collections/CreateCollectionDialog'
);
const { SchemaFieldBuilder } = await import('../components/prompts/SchemaFieldBuilder');

const URL = '/api/images/collections/c1/pipeline';

function overview(): PipelineOverview {
  return {
    config: { steps: { exif: { enabled: true } } },
    preset_id: null,
    steps: [
      { id: 'exif', installed: true, state: 'ok', enabled: true, params: {}, version: 1, params_schema: { properties: {} } },
      {
        id: 'quality',
        installed: true,
        state: 'ok',
        enabled: false,
        params: {},
        version: 1,
        params_schema: { properties: { min_width: { type: 'integer', default: 640 } } },
      },
    ],
    status: {},
    stale: 0,
    not_installed: 0,
    pending: 0,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(toast).mockClear();
});

const testid = (id: string) => `[data-testid="${id}"]`;

describe('pipeline tab (test report B5-B7)', () => {
  it('B6: undoing a change leaves nothing to save', async () => {
    stubFetch({ [`GET ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    const save = () => view.find(testid('images-pipeline-save')) as HTMLButtonElement;
    expect(save().disabled).toBe(true);
    await click(view.find(testid('images-step-toggle-quality')));
    expect(save().disabled).toBe(false);
    await click(view.find(testid('images-step-toggle-quality')));
    expect(save().disabled).toBe(true);
    await view.unmount();
  });

  it('B6: drafts compare by content, not key order', () => {
    const data = overview();
    const drafts = {
      quality: { params: {}, enabled: false },
      exif: { params: {}, enabled: true },
    };
    expect(changed(data, drafts)).toBe(false);
    expect(changed(data, { ...drafts, exif: { enabled: false, params: {} } })).toBe(true);
  });

  it('B5: a cleared field shows its default as the placeholder', async () => {
    stubFetch({ [`GET ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    const input = view.find('#images-param-quality-min_width') as HTMLInputElement;
    expect(input.value).toBe('');
    expect(input.placeholder).toBe('640');
    await setValue(input, '800');
    await setValue(input, '');
    expect(input.value).toBe('');
    await view.unmount();
  });

  it('B7: re-running everything asks first', async () => {
    const calls = stubFetch({
      [`GET ${URL}`]: overview(),
      [`POST ${URL}/restart`]: { status: 'accepted', scope: 'all' },
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    await click(view.find(testid('images-pipeline-restart-all')));
    await flush();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain('AI steps included');
    const buttons = Array.from(dialog?.querySelectorAll('button') ?? []);
    await click(buttons[buttons.length - 1] as HTMLElement);
    await flush();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ scope: 'all' });
    await view.unmount();
  });
});

describe('B4: prompt answer fields', () => {
  it('flags a name two fields share', async () => {
    const field = { type: 'string' as const, description: '', required: false, choices: [] };
    const view = await mount(
      <SchemaFieldBuilder
        fields={[
          { ...field, name: 'a b!' },
          { ...field, name: ' a b! ' },
          { ...field, name: 'c' },
        ]}
        onChange={() => {}}
      />,
    );
    expect(view.find(testid('images-schema-field-duplicate-0'))).not.toBeNull();
    expect(view.find(testid('images-schema-field-duplicate-1'))?.textContent).toContain(
      'already called “a b!”',
    );
    expect(view.find(testid('images-schema-field-duplicate-2'))).toBeNull();
    await view.unmount();
  });
});

describe('B8: the New collection dialog', () => {
  it('forgets what was typed when cancelled', async () => {
    const view = await mount(<CreateCollectionDialog canPublish={false} />);
    await click(view.find(testid('images-new-collection')));
    const name = () => document.querySelector('#images-create-name') as HTMLInputElement;
    await setValue(name(), 'Draft');
    expect(name().value).toBe('Draft');
    const cancel = Array.from(document.querySelectorAll('[role="dialog"] button')).find((b) =>
      (b.textContent ?? '').includes('Cancel'),
    );
    await click(cancel as HTMLElement);
    await click(view.find(testid('images-new-collection')));
    expect(name().value).toBe('');
    await view.unmount();
  });
});

describe('B9: import controls', () => {
  it('says the restart was accepted', async () => {
    stubFetch({
      'GET /api/images/collections/c1/imports': { items: [job({ status: 'completed' })] },
      'POST /api/images/imports/j1/restart': () => job({ status: 'completed' }),
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    await click(view.find(testid('images-import-restart')));
    await flush();
    expect(toast).toHaveBeenCalledWith('Import restarted');
    await view.unmount();
  });
});
