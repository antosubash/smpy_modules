// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PipelineTab, payloadOf } from '../components/pipeline/PipelineTab';
import type { PipelineOverview } from '../utils/types';
import { flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const URL = '/api/images/collections/c1/pipeline';

function overview(overrides: Partial<PipelineOverview> = {}): PipelineOverview {
  return {
    config: { steps: { exif: { enabled: true } } },
    preset_id: null,
    steps: [
      {
        id: 'exif',
        installed: true,
        state: 'ok',
        enabled: true,
        params: {},
        version: 1,
        params_schema: { properties: {} },
      },
      {
        id: 'quality',
        installed: true,
        state: 'ok',
        enabled: false,
        params: {},
        version: 1,
        requires: ['exif'],
        params_schema: {
          properties: {
            min_score: { type: 'number', title: 'Minimum score', default: 0.5 },
            mode: { type: 'string', enum: ['fast', 'slow'], default: 'fast' },
            strict: { type: 'boolean', default: false },
            tags: { type: 'array', items: { type: 'string' } },
            nested: { type: 'object' },
          },
        },
      },
      { id: 'ghost', installed: false, state: 'not_installed', enabled: true },
    ],
    status: {},
    stale: 0,
    not_installed: 0,
    pending: 0,
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

const get = (view: { find: (s: string) => HTMLElement | null }, id: string) =>
  view.find(`[data-testid="${id}"]`);

describe('PipelineTab', () => {
  it('renders toggles, a typed params form and a warning for a step that is not installed', async () => {
    stubFetch({ [`GET ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    expect(get(view, 'images-step-toggle-exif')?.getAttribute('aria-checked')).toBe('true');
    expect(get(view, 'images-step-toggle-quality')?.getAttribute('aria-checked')).toBe('false');
    expect(get(view, 'images-step-missing-ghost')).not.toBeNull();
    expect(get(view, 'images-step-missing-exif')).toBeNull();
    const form = get(view, 'images-params-quality');
    expect(form?.querySelector('input[type="number"]')).not.toBeNull();
    expect(form?.querySelector('select')?.textContent).toContain('slow');
    expect(form?.querySelector('input[type="checkbox"]')).not.toBeNull();
    expect(form?.querySelectorAll('textarea')).toHaveLength(2); // tags, and the JSON fallback
    await view.unmount();
  });

  it('saves the toggled step with its params, then prompts a restart', async () => {
    const calls = stubFetch({
      [`GET ${URL}`]: overview(),
      [`PUT ${URL}`]: () =>
        overview({ config: { steps: { exif: { enabled: true }, quality: { enabled: true } } } }),
      [`POST ${URL}/restart`]: { status: 'accepted', scope: 'stale' },
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    expect(get(view, 'images-pipeline-offer')).toBeNull();
    await click(get(view, 'images-step-toggle-quality'));
    await setValue(view.find('#images-param-quality-min_score') as HTMLInputElement, '0.8');
    await click(get(view, 'images-pipeline-save'));
    await flush();

    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.body).toEqual({
      steps: {
        exif: { enabled: true },
        quality: { enabled: true, min_score: 0.8 },
      },
    });
    expect(get(view, 'images-pipeline-offer')).not.toBeNull();

    await click(get(view, 'images-pipeline-restart-stale'));
    await flush();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ scope: 'stale' });
    expect(get(view, 'images-pipeline-offer')).toBeNull();
    await view.unmount();
  });

  it('keeps an invalid JSON draft out of the saved payload', async () => {
    const calls = stubFetch({ [`GET ${URL}`]: overview(), [`PUT ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    await click(get(view, 'images-step-toggle-quality'));
    await setValue(view.find('#images-param-quality-nested') as HTMLTextAreaElement, '{oops');
    expect(view.host.textContent).toContain('not valid JSON');
    await click(get(view, 'images-pipeline-save'));
    await flush();
    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.body).toEqual({ steps: { exif: { enabled: true }, quality: { enabled: true } } });
    await view.unmount();
  });

  it('does not render a param named __proto__ or constructor', async () => {
    const hostile =
      JSON.parse(`{"id":"safe","installed":true,"state":"ok","enabled":true,"params":{},
      "params_schema":{"properties":{"__proto__":{"type":"string"},"constructor":{"type":"string"},"ok":{"type":"string"}}}}`);
    stubFetch({ [`GET ${URL}`]: overview({ steps: [hostile], config: { steps: {} } }) });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    const ids = view.all('[data-testid="images-params-safe"] input').map((i) => i.id);
    expect(ids).toEqual(['images-param-safe-ok']);
    await view.unmount();
  });

  it('builds the payload on a prototype-less object, so a step id __proto__ is just a key', () => {
    const data = overview({
      steps: [{ id: '__proto__', installed: true, state: 'ok', enabled: true, params: {} }],
      config: { steps: {} },
    });
    const drafts = JSON.parse('{"__proto__":{"enabled":true,"params":{}}}');
    const sent = payloadOf(data, drafts);
    expect(Object.getPrototypeOf(sent)).toBeNull();
    expect(Object.keys(sent)).toEqual(['__proto__']);
    expect(({} as Record<string, unknown>).enabled).toBeUndefined();
  });

  it('shows the stale and not-installed banners and the restart buttons', async () => {
    const calls = stubFetch({
      [`GET ${URL}`]: overview({ stale: 3, not_installed: 2 }),
      [`POST ${URL}/restart`]: { status: 'accepted', scope: 'failed' },
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    expect(get(view, 'images-pipeline-stale')?.textContent).toContain('3 results');
    expect(get(view, 'images-pipeline-not-installed')?.textContent).toContain('2 results');
    await click(get(view, 'images-pipeline-restart-failed'));
    await flush();
    expect(
      calls.some((c) => c.method === 'POST' && (c.body as { scope: string }).scope === 'failed'),
    ).toBe(true);
    await view.unmount();
  });

  it('removes a step that is not installed from the saved payload, with an undo', async () => {
    const saved = { exif: { enabled: true }, ghost: { enabled: true, level: 3 } };
    const calls = stubFetch({
      [`GET ${URL}`]: overview({ config: { steps: saved } }),
      [`PUT ${URL}`]: () => overview({ config: { steps: { exif: { enabled: true } } } }),
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    expect(get(view, 'images-pipeline-save')?.hasAttribute('disabled')).toBe(true);
    await click(get(view, 'images-step-remove-ghost'));
    expect(get(view, 'images-step-removed-ghost')).not.toBeNull();
    await click(get(view, 'images-step-undo-ghost'));
    expect(get(view, 'images-step-removed-ghost')).toBeNull();
    await click(get(view, 'images-step-remove-ghost'));
    await click(get(view, 'images-pipeline-save'));
    await flush();
    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.body).toEqual({ steps: { exif: { enabled: true } } });
    await view.unmount();
  });

  it('keeps a missing step exactly as saved unless it is removed', () => {
    const data = overview({
      config: { steps: { exif: { enabled: true }, ghost: { enabled: true, level: 3 } } },
    });
    const drafts = {
      exif: { enabled: true, params: {} },
      quality: { enabled: false, params: {} },
      ghost: { enabled: true, params: {} },
    };
    expect(payloadOf(data, drafts).ghost).toEqual({ enabled: true, level: 3 });
    expect(
      'ghost' in payloadOf(data, { ...drafts, ghost: { ...drafts.ghost, removed: true } }),
    ).toBe(false);
  });

  it('offers no remove action without manage rights', async () => {
    stubFetch({ [`GET ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={false} />);
    await flush();
    expect(get(view, 'images-step-remove-ghost')).toBeNull();
    await view.unmount();
  });

  it('is read-only without manage rights', async () => {
    stubFetch({ [`GET ${URL}`]: overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={false} />);
    await flush();
    expect(get(view, 'images-pipeline-save')).toBeNull();
    expect(get(view, 'images-pipeline-restart-all')).toBeNull();
    expect(get(view, 'images-step-toggle-exif')?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });
});
