import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearExtensions,
  eventType,
  registerEventType,
  registerRegistration,
  registerSource,
  registerToolbarItem,
  registrationFor,
  registrations,
  source,
  toolbarItems,
} from './registry';

const lazy = () => Promise.resolve({ default: () => null });

beforeEach(clearExtensions);

describe('registry', () => {
  it('throws on a duplicate id, per kind', () => {
    registerEventType({ id: 'acme:talk' });
    expect(() => registerEventType({ id: 'acme:talk' })).toThrow(/acme:talk/);
    registerSource({ id: 'acme:talk' }); // a source may share an id with a type
    expect(() => registerSource({ id: 'acme:talk' })).toThrow(/acme:talk/);
    registerToolbarItem({ id: 't', placement: 'end', surfaces: ['console'], Component: lazy });
    expect(() =>
      registerToolbarItem({ id: 't', placement: 'start', surfaces: ['public'], Component: lazy }),
    ).toThrow(/t/);
  });

  it('registers a registration provider by id, lazily, once', () => {
    registerRegistration({ id: 'acme:forms', EditorSection: lazy, PublicPanel: lazy });
    expect(() => registerRegistration({ id: 'acme:forms' })).toThrow(/acme:forms/);
    expect(() => registerRegistration({ id: '' })).toThrow();
    const found = registrationFor('acme:forms');
    expect(found?.EditorSection).toBe(registrationFor('acme:forms')?.EditorSection);
    expect(found?.PublicPanel).toBeDefined();
    expect(registrationFor('nope')).toBeUndefined();
    registerRegistration({ id: 'a:first' });
    expect(registrations().map((r) => r.id)).toEqual(['a:first', 'acme:forms']);
    registerEventType({ id: 'acme:forms' }); // a type may share an id with a registration
  });

  it('refuses an empty id', () => {
    expect(() => registerEventType({ id: '' })).toThrow();
  });

  it('returns lazy-wrapped components, the same object each time', () => {
    registerEventType({ id: 'acme:talk', Chip: lazy, PublicDetail: lazy });
    const a = eventType('acme:talk');
    const b = eventType('acme:talk');
    expect(a?.Chip).toBeDefined();
    expect(a?.Chip).toBe(b?.Chip);
    expect(a?.EditorSection).toBeUndefined();
    const chip = a?.Chip as unknown as { $$typeof: symbol };
    expect(typeof chip.$$typeof).toBe('symbol'); // React.lazy
    expect(eventType('nope')).toBeUndefined();
    registerSource({ id: 'acme:s', SettingsSection: lazy });
    const first = source('acme:s')?.SettingsSection;
    expect(first).toBeDefined();
    expect(first).toBe(source('acme:s')?.SettingsSection);
  });

  it('filters toolbar items by surface and placement and sorts them by id', () => {
    registerToolbarItem({ id: 'b', placement: 'end', surfaces: ['console'], Component: lazy });
    registerToolbarItem({
      id: 'a',
      placement: 'end',
      surfaces: ['console', 'public'],
      Component: lazy,
    });
    registerToolbarItem({ id: 'c', placement: 'start', surfaces: ['console'], Component: lazy });
    expect(toolbarItems('end', 'console').map((i) => i.id)).toEqual(['a', 'b']);
    expect(toolbarItems('end', 'public').map((i) => i.id)).toEqual(['a']);
    expect(toolbarItems('start', 'public')).toEqual([]);
    expect(toolbarItems('start', 'console').map((i) => i.id)).toEqual(['c']);
  });
});
