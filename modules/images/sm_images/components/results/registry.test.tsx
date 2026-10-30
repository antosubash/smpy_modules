// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';

import { registerResultView as publicRegister } from '../../index';
import { mount } from '../../page-tests/test-dom';
import { ResultView } from './ResultView';
import { clearResultViews, getResultView, registerResultView } from './registry';

afterEach(clearResultViews);

const Mine = ({ id, image }: { id: string; image: unknown }) => (
  <p data-testid="mine">
    custom {id} {image === null ? 'noimage' : ''}
  </p>
);
const run = {
  step: 'exif',
  status: 'completed',
  step_version: 1,
  error_code: null,
  error_message: null,
  finished_at: null,
  output: { make: 'Canon' },
};

describe('result view registry', () => {
  it('is exported from the package entry point', () => {
    expect(publicRegister).toBe(registerResultView);
  });

  it('throws on a duplicate (kind, id) but allows the same id under another kind', () => {
    registerResultView({ kind: 'step', id: 'exif', component: Mine });
    expect(() => registerResultView({ kind: 'step', id: 'exif', component: Mine })).toThrow(
      /already registered/,
    );
    registerResultView({ kind: 'prompt_result', id: 'exif', component: Mine });
    expect(getResultView('cross_check', 'exif')).toBeUndefined();
  });

  it('renders the registered view, else the generic fallback', async () => {
    registerResultView({ kind: 'step', id: 'exif', component: Mine });
    const custom = await mount(
      <ResultView kind="step" id="exif" output={run.output} run={run} image={null} />,
    );
    expect(custom.find('[data-testid="mine"]')?.textContent).toContain('custom exif noimage');
    await custom.unmount();

    const other = await mount(
      <ResultView
        kind="step"
        id="quality"
        output={{ score: 0.5 }}
        run={{ ...run, step: 'quality' }}
        image={null}
      />,
    );
    const generic = other.find('[data-testid="images-result-generic"]');
    expect(generic?.textContent).toContain('quality');
    expect(generic?.textContent).toContain('0.5');
    await other.unmount();
  });

  it('does not call a completed step with no output withheld for an editor', async () => {
    const view = await mount(
      <ResultView
        kind="step"
        id="exif"
        output={null}
        run={{ ...run, output_visible: true }}
        image={null}
      />,
    );
    expect(view.host.textContent).not.toContain('only shown to people');
    await view.unmount();
  });

  it('shows a generic view without output as withheld, not as empty', async () => {
    const view = await mount(
      <ResultView
        kind="step"
        id="exif"
        output={null}
        run={{ ...run, output_visible: false }}
        image={null}
      />,
    );
    expect(view.host.textContent).toContain('only shown to people who can edit');
    await view.unmount();
  });
});
