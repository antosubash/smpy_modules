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
let incomplete = false;
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
        onIncomplete={(value) => {
          incomplete = value;
        }}
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

  it('clearing the last date keeps the controls, shows the error and reports it', async () => {
    const view = await mount(<Harness initial="FREQ=WEEKLY;UNTIL=20261231;BYDAY=MO" />);
    await setValue(field('event-rrule-until'), '');
    expect(last).toBe('FREQ=WEEKLY;BYDAY=MO');
    expect(field('event-rrule-end').value).toBe('until');
    expect(field('event-rrule-until').getAttribute('aria-invalid')).toBe('true');
    expect(view.host.textContent).toContain('This field is required.');
    expect(incomplete).toBe(true);
    await click(document.getElementById('event-rrule-day-WE'));
    expect(last).toBe('FREQ=WEEKLY;BYDAY=MO,WE');
    expect(field('event-rrule-until')).toBeTruthy();
    expect(incomplete).toBe(true);
    await setValue(field('event-rrule-until'), '2026-12-31');
    expect(last).toBe('FREQ=WEEKLY;UNTIL=20261231;BYDAY=MO,WE');
    expect(incomplete).toBe(false);
    await view.unmount();
  });

  it('leaving "on a date" for never drops the pending end', async () => {
    const view = await mount(<Harness initial="FREQ=DAILY;UNTIL=20261231" />);
    await setValue(field('event-rrule-until'), '');
    await setValue(field('event-rrule-end'), 'never');
    expect(view.host.querySelector('#event-rrule-until')).toBeNull();
    expect(incomplete).toBe(false);
    await view.unmount();
  });

  it('a stored rule the form cannot express is read-only until edited, and is not rewritten', async () => {
    const raw = 'FREQ=MONTHLY;BYMONTHDAY=1,15;BYSETPOS=1';
    const view = await mount(<Harness initial={raw} />);
    expect(field('event-rrule-text').hasAttribute('readonly')).toBe(true);
    expect(view.host.textContent).toContain('kept exactly as stored');
    expect(last).toBe(raw);
    await click(view.button('Edit as text'));
    expect(field('event-rrule-text').hasAttribute('readonly')).toBe(false);
    expect(last).toBe(raw);
    await view.unmount();
  });

  it('picking a repeat replaces a custom rule explicitly', async () => {
    const view = await mount(<Harness initial="FREQ=DAILY;INTERVAL=100" />);
    await setValue(field('event-rrule-mode'), 'WEEKLY');
    expect(last).toBe('FREQ=WEEKLY;BYDAY=MO');
    await view.unmount();
  });

  it('limits the custom text to the backend length', async () => {
    const view = await mount(<Harness initial="FREQ=DAILY;BYSETPOS=1" />);
    expect(field('event-rrule-text').getAttribute('maxlength')).toBe('500');
    await view.unmount();
  });
});
