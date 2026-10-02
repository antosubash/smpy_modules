import { describe, expect, it } from 'vitest';
import { CodeBlock, FactsBlock, TableBlock, TimelineBlock } from './data';
import { renderBlock } from './renderBlock';

const ROWS = 'Site | Sensors\nNorth | 12\nSouth | 9';

describe('Table', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(TableBlock)).toBe('');
  });

  it('promotes the first row to a header by default', () => {
    const markup = renderBlock(TableBlock, { rows: ROWS });
    expect(markup).toContain('<thead>');
    expect(markup).toContain('scope="col"');
    expect(markup).toContain('>Site</th>');
    expect(markup).toContain('>North</td>');
  });

  it('keeps the first row as data when told to', () => {
    const markup = renderBlock(TableBlock, { rows: ROWS, header: false });
    expect(markup).not.toContain('<thead>');
    expect(markup).toContain('>Site</td>');
  });

  it('lets a short row stay short instead of padding it', () => {
    // A table that quietly reshapes what was typed is harder to correct than
    // one that looks wrong.
    const markup = renderBlock(TableBlock, { rows: 'a | b | c\nd | e', header: false });
    expect(markup.match(/<td/g)).toHaveLength(5);
  });

  it('scrolls inside its own box so a wide table cannot push the story sideways', () => {
    expect(renderBlock(TableBlock, { rows: ROWS })).toContain('overflow-x-auto');
  });

  it('lines figures up in a column', () => {
    expect(renderBlock(TableBlock, { rows: ROWS })).toContain('tabular-nums');
  });
});

describe('Code', () => {
  it('renders nothing without code', () => {
    expect(renderBlock(CodeBlock)).toBe('');
    expect(renderBlock(CodeBlock, { code: '  \n ' })).toBe('');
  });

  it('renders the code verbatim inside pre/code', () => {
    const markup = renderBlock(CodeBlock, { code: 'make test-py' });
    expect(markup).toContain('<pre');
    expect(markup).toContain('<code>make test-py</code>');
  });

  it('escapes markup rather than emitting it', () => {
    // The whole point of the block is quoting something exactly; a payload
    // containing a tag must not become one.
    const markup = renderBlock(CodeBlock, { code: '<script>alert(1)</script>' });
    expect(markup).toContain('&lt;script&gt;');
    expect(markup).not.toContain('<script>');
  });

  it('shows the language as a label only when one is given', () => {
    expect(renderBlock(CodeBlock, { code: 'x', language: 'bash' })).toContain('bash');
    expect(renderBlock(CodeBlock, { code: 'x' })).not.toContain('font-mono text-xs');
  });

  it('scrolls a long line rather than wrapping it', () => {
    expect(renderBlock(CodeBlock, { code: 'x' })).toContain('overflow-x-auto');
  });
});

describe('Key figures', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(FactsBlock)).toBe('');
  });

  it('puts the figure above its label, as a description list', () => {
    const markup = renderBlock(FactsBlock, { items: '21 | sensors installed\n4 | plots' });
    expect(markup).toContain('<dl');
    expect(markup).toContain('21');
    expect(markup).toContain('sensors installed');
    expect(markup).toContain('4');
  });

  it('lines the figures up as numerals', () => {
    expect(renderBlock(FactsBlock, { items: '21 | sensors' })).toContain('tabular-nums');
  });

  it('wraps rather than forcing a row, so three figures survive a phone', () => {
    expect(renderBlock(FactsBlock, { items: '1 | a' })).toContain('flex-wrap');
  });

  it('renders a figure with no label', () => {
    expect(renderBlock(FactsBlock, { items: '21' })).toContain('21');
  });
});

describe('Timeline', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(TimelineBlock)).toBe('');
  });

  it('pairs each entry with when it happened', () => {
    const markup = renderBlock(TimelineBlock, {
      items: 'March 2024 | The survey began\nJune | Two more plots added',
    });
    expect(markup).toContain('March 2024');
    expect(markup).toContain('The survey began');
    expect(markup).toContain('Two more plots added');
  });

  it('accepts an entry with no date', () => {
    // Reporting deals in "some time before 2019"; a row with nothing usable
    // still belongs in the sequence.
    const markup = renderBlock(TimelineBlock, { items: 'Something happened' });
    expect(markup).toContain('Something happened');
  });

  it('is an ordered list, because the order is the content', () => {
    expect(renderBlock(TimelineBlock, { items: 'a | b' })).toContain('<ol');
  });

  it('hides the decorative markers from a screen reader', () => {
    expect(renderBlock(TimelineBlock, { items: 'a | b' })).toContain('aria-hidden="true"');
  });
});
