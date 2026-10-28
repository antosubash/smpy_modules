// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { collection, image, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const Image = (await import('../pages/Image')).default;

const props = { collection: collection(), can_edit: true, can_manage: true };

afterEach(() => vi.unstubAllGlobals());

describe('Image viewer', () => {
  it('shows the display copy and no original toggle without can_view_original', async () => {
    const calls = stubFetch({});
    const view = await mount(<Image image={image('i1')} can_view_original={false} {...props} />);
    const img = view.find<HTMLImageElement>('[data-testid="images-viewer-image"]');
    expect(img?.getAttribute('src')).toBe('/api/images/images/i1/display?v=1');
    expect(view.find('[data-testid="images-original-toggle"]')).toBeNull();
    expect(view.host.innerHTML).not.toContain('/original');
    expect(calls).toHaveLength(0);
    await view.unmount();
  });

  it('references the original only after the toggle, and toggles back', async () => {
    const view = await mount(<Image image={image('i1')} can_view_original={true} {...props} />);
    const toggle = () => view.find('[data-testid="images-original-toggle"]');
    expect(view.host.innerHTML).not.toContain('/original');
    await click(toggle());
    expect(view.find('[data-testid="images-viewer-image"]')?.getAttribute('src')).toBe(
      '/api/images/images/i1/original',
    );
    await click(toggle());
    expect(view.find('[data-testid="images-viewer-image"]')?.getAttribute('src')).toBe(
      '/api/images/images/i1/display?v=1',
    );
    await view.unmount();
  });

  it('lists the metadata and the properties as results', async () => {
    const view = await mount(
      <Image
        image={image('i1', { camera_make: 'Canon', camera_model: 'R5', properties: { tree: 'oak' } })}
        can_view_original={false}
        {...props}
      />,
    );
    const meta = view.find('[data-testid="images-meta"]')?.textContent ?? '';
    expect(meta).toContain('i1.jpg');
    expect(meta).toContain('800 × 600');
    expect(meta).toContain('Canon R5');
    expect(view.find('[data-testid="images-results"]')?.textContent).toContain('oak');
    await view.unmount();
  });

  it('renders each step run through ResultView, registered view first', async () => {
    const { registerResultView, clearResultViews } = await import('../components/results/registry');
    registerResultView({
      kind: 'step',
      id: 'exif',
      component: ({ output }) => <p data-testid="exif-view">{String(output?.make)}</p>,
    });
    const run = (step: string, output: Record<string, unknown> | null) => ({
      step,
      status: 'completed',
      step_version: 1,
      error_code: null,
      error_message: null,
      finished_at: null,
      output,
    });
    const view = await mount(
      <Image
        image={image('i1', { step_runs: [run('exif', { make: 'Canon' }), run('quality', { score: 7 })] })}
        can_view_original={false}
        {...props}
      />,
    );
    expect(view.find('[data-testid="exif-view"]')?.textContent).toBe('Canon');
    expect(view.find('[data-testid="images-result-generic"]')?.textContent).toContain('quality');
    await view.unmount();
    clearResultViews();
  });

  it('offers deletion only to someone who may manage the collection', async () => {
    const view = await mount(
      <Image image={image('i1')} can_view_original={false} {...props} can_manage={false} />,
    );
    expect(view.find('[data-testid="images-delete-image"]')).toBeNull();
    await view.unmount();
  });
});
