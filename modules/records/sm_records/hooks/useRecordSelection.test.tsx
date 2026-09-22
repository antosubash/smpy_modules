// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest';

import { act, click, mount } from '../test-dom';

const { useRecordSelection } = await import('./useRecordSelection');

/** A probe: one button per row, so a click is a toggle and Shift+click is a
 *  range — the two gestures the hook exists to interpret. */
function Probe({ uuids }: { uuids: string[] }) {
  const selection = useRecordSelection(uuids);
  return (
    <div>
      <output data-testid="picked">{selection.uuids.join(',')}</output>
      <span data-testid="flags">
        {String(selection.allSelected)}/{String(selection.someSelected)}
      </span>
      {uuids.map((uuid) => (
        <button
          key={uuid}
          type="button"
          data-testid={`row-${uuid}`}
          onClick={(event) => selection.toggle(uuid, event.shiftKey)}
        >
          {uuid}
        </button>
      ))}
      <button type="button" data-testid="all" onClick={selection.toggleAll}>
        all
      </button>
      <button type="button" data-testid="clear" onClick={selection.clear}>
        clear
      </button>
      <button type="button" data-testid="deselect" onClick={() => selection.deselect(['b'])}>
        deselect b
      </button>
    </div>
  );
}

const PAGE = ['a', 'b', 'c', 'd'];

describe('useRecordSelection', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('collects what is clicked, in page order rather than click order', async () => {
    const view = await mount(<Probe uuids={PAGE} />);

    await click(view.find('[data-testid="row-c"]'));
    await click(view.find('[data-testid="row-a"]'));

    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a,c');
  });

  it('select-all ticks the page, and again clears it', async () => {
    const view = await mount(<Probe uuids={PAGE} />);

    await click(view.find('[data-testid="all"]'));
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a,b,c,d');
    expect(view.find('[data-testid="flags"]')?.textContent).toBe('true/false');

    await click(view.find('[data-testid="all"]'));
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('');
  });

  it('reports a half-ticked page as indeterminate', async () => {
    const view = await mount(<Probe uuids={PAGE} />);
    await click(view.find('[data-testid="row-b"]'));
    expect(view.find('[data-testid="flags"]')?.textContent).toBe('false/true');
  });

  it('Shift+click fills in from the last row clicked', async () => {
    const view = await mount(<Probe uuids={PAGE} />);

    await click(view.find('[data-testid="row-a"]'));
    const target = view.find('[data-testid="row-d"]');
    // The gesture, not a prop: the handler reads `shiftKey` off the event.
    await act(async () => {
      target?.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    });

    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a,b,c,d');
  });

  it('drops the selection when the page underneath changes', async () => {
    const view = await mount(<Probe uuids={PAGE} />);
    await click(view.find('[data-testid="row-a"]'));
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a');

    // A sort, a filter, a page step or a reload after a mutation: "12
    // selected" must never mean rows nobody can see.
    await view.render(<Probe uuids={['x', 'y']} />);

    expect(view.find('[data-testid="picked"]')?.textContent).toBe('');
  });

  it('keeps the selection when the same rows render again', async () => {
    const view = await mount(<Probe uuids={PAGE} />);
    await click(view.find('[data-testid="row-a"]'));
    await view.render(<Probe uuids={[...PAGE]} />);
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a');
  });

  it('deselects exactly what a refusal named, keeping the rest ticked', async () => {
    const view = await mount(<Probe uuids={PAGE} />);
    await click(view.find('[data-testid="all"]'));

    await click(view.find('[data-testid="deselect"]'));

    expect(view.find('[data-testid="picked"]')?.textContent).toBe('a,c,d');
  });

  it('clears everything on demand', async () => {
    const view = await mount(<Probe uuids={PAGE} />);
    await click(view.find('[data-testid="all"]'));
    await click(view.find('[data-testid="clear"]'));
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('');
  });
});
