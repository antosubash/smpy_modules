// @vitest-environment happy-dom

import { type Data, Render } from '@puckeditor/core';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetBlockRegistry } from './blockRegistry';
import { migrateContent } from './migrateContent';
import { getPuckConfig } from './puckConfig';

/**
 * A page that holds a block another module contributed (an events block) must still render on a
 * host where that module is not installed: the registry has no such block, and the page keeps
 * its stored props. Puck draws nothing for a type its config does not know (the editor's canvas
 * shows its neutral "No configuration for <type>" instead), so the rest of the page stands.
 */
describe('a stored block whose module is not installed', () => {
  beforeEach(() => resetBlockRegistry());

  const stored = {
    root: { props: { title: 'Home' } },
    content: [
      { type: 'Heading', props: { id: 'h1', text: 'Welcome' } },
      {
        type: 'UpcomingEvents',
        props: { id: 'ev1', heading: 'Upcoming events', calendars: [{ slug: 'team' }], count: 7 },
      },
      { type: 'Heading', props: { id: 'h2', text: 'After the events' } },
    ],
    zones: {},
  } as unknown as Data;

  it('is not in the config, and the page renders the blocks around it', () => {
    const config = getPuckConfig();
    expect(Object.keys(config.components)).not.toContain('UpcomingEvents');
    const html = renderToStaticMarkup(
      <Render config={config} data={migrateContent(stored, config)} />,
    );
    expect(html).toContain('Welcome');
    expect(html).toContain('After the events');
    expect(html).not.toContain('Upcoming events');
  });

  it('keeps the stored props when the page is migrated for the editor', () => {
    const config = getPuckConfig();
    const migrated = migrateContent(structuredClone(stored), config);
    expect(migrated.content[1]).toEqual(stored.content[1]);
  });
});
