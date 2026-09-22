// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { click, mount, setValue } from '../../test-dom';
import { FieldList } from './FieldList';
import { withUids } from './formHelpers';
import type { EditableField } from './types';

function saved(key: string): EditableField {
  return {
    key,
    uid: `uid-${key}`,
    fromServer: true,
    type: 'text',
    label: key,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
  };
}

/** `FieldList` owns `fields` through its `onChange` callback, so the test
 *  plays the page: it holds the list and re-renders with what came back. */
async function mountList(initial: EditableField[]) {
  let fields = initial;
  const view = await mount(
    <FieldList fields={fields} targetTypes={[]} disabled={false} errors={[]} onChange={() => {}} />,
  );
  const rerender = async () => {
    await view.render(
      <FieldList
        fields={fields}
        targetTypes={[]}
        disabled={false}
        errors={[]}
        onChange={async (next) => {
          fields = next;
          await rerender();
        }}
      />,
    );
  };
  await rerender();
  return { view, current: () => fields };
}

describe('FieldList — R1: the key lock follows the row, not the key text', () => {
  it('keeps a brand-new row editable when its key collides with a saved one', async () => {
    const { view } = await mountList([saved('title')]);

    await click(view.button('Add field'));
    // The new row opens expanded; its inputs are the second row's.
    const newKey = view.find<HTMLInputElement>('#field-row-1-key');
    expect(newKey).not.toBeNull();
    expect(newKey?.disabled).toBe(false);

    await setValue(newKey as HTMLInputElement, 'title');

    const after = view.find<HTMLInputElement>('#field-row-1-key');
    // Still editable — the whole point: before R1 this input went
    // `disabled` + `readOnly` the moment the text matched an existing key,
    // and "Remove field" was the only way out of the typo.
    expect(after?.value).toBe('title');
    expect(after?.disabled).toBe(false);
    expect(after?.readOnly).toBe(false);
    // …and the row says what is wrong instead.
    expect(view.host.innerHTML).toContain('Another field already uses this key.');
    // The lock's own help text is not claiming this field has been created.
    expect(view.host.innerHTML).not.toContain("Can't be changed after the field is created.");

    view.unmount();
  });

  it('still locks a row that came off the wire', async () => {
    const { view } = await mountList(withUids([saved('title')]));
    // Expand the saved row: its summary button toggles the body.
    await click(view.find('[data-testid="records-field-row"] button'));
    const key = view.find<HTMLInputElement>('#field-row-0-key');
    expect(key?.disabled).toBe(true);
    expect(key?.readOnly).toBe(true);
    expect(view.host.innerHTML).toContain("Can't be changed after the field is created.");
    view.unmount();
  });
});

describe('withUids — R1', () => {
  it('marks every field it takes off the wire as fromServer', () => {
    expect(withUids([saved('a'), saved('b')]).every((f) => f.fromServer)).toBe(true);
  });
});
