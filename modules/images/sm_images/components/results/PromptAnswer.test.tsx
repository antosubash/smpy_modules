// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { click, mount } from '../../test-dom';
import { TEXT_SHOWN } from './PromptAnswer';
import { ResultView } from './ResultView';

const step = 'prompt:646b48c4';
const run = {
  step,
  label: 'Land cover',
  status: 'completed',
  step_version: 1,
  error_code: null,
  error_message: null,
  finished_at: null,
  output: { model: 'qwen', structured: true },
  output_visible: true,
};

describe("a prompt step's answer in the viewer (QA retest 2, R2-VIEW-ANSWER)", () => {
  it('lists a structured answer as fields, not the run bookkeeping', async () => {
    const answered = {
      ...run,
      answer: { data: { land_cover: 'forest', confidence: 0.95 }, text: null },
    };
    const view = await mount(
      <ResultView kind="step" id={step} output={run.output} run={answered} image={null} />,
    );
    const terms = view.all('dt').map((d) => d.textContent);
    expect(terms).toEqual(['land_cover', 'confidence']);
    expect(view.all('dd').map((d) => d.textContent)).toEqual(['forest', '0.95']);
    expect(view.host.textContent).not.toContain('structured');
    await view.unmount();
  });

  it('shows free text, bounded, with a way to read all of it', async () => {
    const long = `${'word '.repeat(400)}END`;
    const answered = { ...run, answer: { data: null, text: long } };
    const view = await mount(
      <ResultView kind="step" id={step} output={run.output} run={answered} image={null} />,
    );
    const text = () => view.find('[data-testid="images-answer-text"]')?.textContent ?? '';
    expect(text().length).toBeLessThanOrEqual(TEXT_SHOWN + 1);
    expect(text()).not.toContain('END');
    await click(view.find('[data-testid="images-answer-more"]'));
    expect(text()).toContain('END');
    await view.unmount();
  });

  it('keeps the generic rows for a run without an answer', async () => {
    const view = await mount(
      <ResultView kind="step" id={step} output={run.output} run={run} image={null} />,
    );
    expect(view.all('dt').map((d) => d.textContent)).toEqual(['model', 'structured']);
    await view.unmount();
  });
});
