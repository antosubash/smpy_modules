// @vitest-environment happy-dom

import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { RecurrenceEditor } from '../components/editor/RecurrenceEditor';
import { field } from './support';
import { click, mount, setValue } from './test-dom';

afterEach(() => {
  document.body.innerHTML = '';
});

let last = '';
function Harness({ initial = '', start = '2026-03-02T10:00', disabled = false, reason = '' }) {
  const [rule, setRule] = useState(initial);
  const [at] = useState(start);
  last = rule;
  return (
    <>
      <RecurrenceEditor
        value={rule}
        start={at}
        timezone="Europe/Vienna"
        disabled={disabled}
        reason={reason}
        onChange={setRule}
      />
      <output id="rule">{rule}</output>
    </>
  );
}

describe('RecurrenceEditor', () => {
  it('summary updates as the form changes', async () => {
    const view = await mount(<Harness />);
    expect(view.host.textContent).not.toContain('Every');
    await setValue(field('event-rrule-mode'), 'DAILY');
    expect(view.host.textContent).toContain('Every day');
    await setValue(field('event-rrule-interval'), '3');
    expect(view.host.textContent).toContain('Every 3 days');
    await setValue(field('event-rrule-end'), 'count');
    await setValue(field('event-rrule-count'), '5');
    expect(view.host.textContent).toContain('Every 3 days, 5 times');
    expect(last).toBe('FREQ=DAILY;INTERVAL=3;COUNT=5');
    await setValue(field('event-rrule-mode'), '');
    expect(last).toBe('');
    await view.unmount();
  });

  it('weekly preselects the start weekday and adds others', async () => {
    const view = await mount(<Harness />);
    await setValue(field('event-rrule-mode'), 'WEEKLY');
    const monday = document.getElementById('event-rrule-day-MO');
    expect(monday?.getAttribute('data-state')).toBe('checked');
    expect(monday?.hasAttribute('disabled')).toBe(true);
    expect(last).toBe('FREQ=WEEKLY;BYDAY=MO');
    await click(document.getElementById('event-rrule-day-WE'));
    expect(last).toBe('FREQ=WEEKLY;BYDAY=MO,WE');
    expect(view.host.textContent).toContain('Every week on Monday and Wednesday');
    await view.unmount();
  });

  it('monthly offers only the patterns the start satisfies', async () => {
    const view = await mount(<Harness initial="FREQ=MONTHLY;BYMONTHDAY=2" />);
    const options = [...field('event-rrule-monthly').querySelectorAll('option')].map(
      (o) => o.textContent,
    );
    expect(options).toEqual(['On day 2', 'On the first Monday']);
    await setValue(field('event-rrule-monthly'), '1');
    expect(last).toBe('FREQ=MONTHLY;BYDAY=1MO');
    await view.unmount();
  });

  it('custom rule shown raw', async () => {
    const raw = 'FREQ=MONTHLY;BYMONTHDAY=1,15;BYSETPOS=1';
    const view = await mount(<Harness initial={raw} />);
    expect(field('event-rrule-text').value).toBe(raw);
    expect(view.host.querySelector('#event-rrule-interval')).toBeNull();
    await setValue(field('event-rrule-text'), 'FREQ=DAILY');
    expect(field('event-rrule-text').value).toBe('FREQ=DAILY'); // stays raw while typing
    await view.unmount();
  });

  it('is disabled with its reason', async () => {
    const view = await mount(<Harness disabled reason="A sub-event cannot repeat." />);
    expect(view.host.textContent).toContain('A sub-event cannot repeat.');
    expect(field('event-rrule-mode').closest('fieldset')?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });
});
