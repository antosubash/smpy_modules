// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { mount } from '../../test-dom';
import { ResultView } from './ResultView';

const run = {
  step: 'exif',
  status: 'completed',
  step_version: 1,
  error_code: null,
  error_message: null,
  finished_at: null,
  output: null,
  output_visible: true,
};

describe('generic result view (QA TEST-014)', () => {
  it('names a prompt step by its prompt, and falls back to the id when it was deleted', async () => {
    const step = 'prompt:646b48c4-0000-4000-8000-000000000000';
    const named = await mount(
      <ResultView
        kind="step"
        id={step}
        output={{ n: 1 }}
        run={{ ...run, step, label: 'Land cover' }}
        image={null}
      />,
    );
    const title = named.find('[data-testid="images-result-title"]');
    expect(title?.textContent).toBe('Land cover');
    expect(title?.getAttribute('title')).toBe(step);
    await named.unmount();

    const orphan = await mount(
      <ResultView
        kind="step"
        id={step}
        output={{ n: 1 }}
        run={{ ...run, step, label: null }}
        image={null}
      />,
    );
    expect(orphan.find('[data-testid="images-result-title"]')?.textContent).toBe(step);
    await orphan.unmount();
  });

  it('gives the EXIF fields human labels, wraps long keys and leaves out empty values', async () => {
    const output = {
      lat: 59.3,
      captured_at: '2024-06-01T10:00:00',
      captured_at_zone_known: false,
      make: 'Canon',
      model: null,
      some_plugin_field: 'x',
    };
    const view = await mount(
      <ResultView kind="step" id="exif" output={output} run={{ ...run, output }} image={null} />,
    );
    const terms = view.all('dt').map((d) => d.textContent);
    expect(terms).toEqual([
      'Latitude',
      'Captured',
      'Time zone known',
      'Camera make',
      'some_plugin_field',
    ]);
    for (const dt of view.all('dt')) expect(dt.className).toContain('break-words');
    await view.unmount();
  });
});
