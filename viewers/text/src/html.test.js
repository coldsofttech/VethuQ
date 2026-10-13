import { describe, expect, it } from 'vitest';
import { HtmlHighlighter, START, formatHtml, locateInHtml, scan } from './html.js';

const rows = (lines) => {
  const h = new HtmlHighlighter(lines);
  return lines.map((_, i) => h.segments(i));
};
const text = (segments) => segments.map(([, t]) => t).join('');

describe('scan', () => {
  it('colours a tag with attributes, entities and text', () => {
    const [row] = rows(['<a href="x.html" class=big>Tom &amp; Jerry</a>']);
    expect(row).toContainEqual(['tag', 'a']);
    expect(row).toContainEqual(['attribute', 'href']);
    expect(row).toContainEqual(['attrvalue', '"x.html"']);
    expect(row).toContainEqual(['attrvalue', 'big']);
    expect(row).toContainEqual(['entity', '&amp;']);
    expect(row).toContainEqual([null, 'Tom ']);
    expect(row.filter(([k]) => k === 'tag').map(([, t]) => t)).toEqual(['a', 'a']);
  });

  it('keeps every line whole', () => {
    for (const line of [
      '<!DOCTYPE html>',
      '<p class="a" id=\'b\'>x < y > z &bogus; &#169;</p>',
      '<br/><img src=a.png alt="">',
      '<!-- note --> text',
      '<',
      '</',
      '<a',
    ]) {
      expect(text(scan(line, START).segments)).toBe(line);
    }
  });

  it('carries a comment, a tag and a quoted value over lines', () => {
    const r = rows(['<!-- one', 'two -->', '<div', '  class="a', '   b"', '  id=x>', 'after']);
    expect(r[1]).toEqual([['comment', 'two -->']]);
    expect(r[3]).toContainEqual(['attribute', 'class']);
    expect(r[4]).toEqual([['attrvalue', '   b"']]);
    expect(r[5].find(([k]) => k === 'attribute')).toEqual(['attribute', 'id']);
    expect(r[6]).toEqual([[null, 'after']]);
  });

  it('colours a style block as CSS and leaves a script plain', () => {
    const r = rows([
      '<style>',
      'a { color: red }',
      '</style>',
      '<script>',
      'if (a < b) { x = "</p>"; }',
      '</script>',
      '<p>done</p>',
    ]);
    expect(r[1].some(([k, t]) => k === 'property' && t === 'color')).toBe(true);
    expect(r[1].some(([k]) => k === 'selector')).toBe(true);
    expect(r[4]).toEqual([[null, 'if (a < b) { x = "</p>"; }']]);
    expect(r[6]).toContainEqual(['tag', 'p']);
    expect(r[2]).toContainEqual(['tag', 'style']);
  });

  it('copes with what is not HTML, and finds the state of a line far down', () => {
    expect(() => rows(['>>>', '<<<', '"', '<!--', '-->', '<style', '</style', ''])).not.toThrow();
    const lines = Array.from({ length: 20000 }, (_, i) => (i === 5000 ? '<!-- open' : '<p>x</p>'));
    const h = new HtmlHighlighter(lines);
    expect(h.segments(5001)[0][0]).toBe('comment');
  });
});

describe('formatHtml', () => {
  it('puts each tag on its own line, indented by element', () => {
    expect(formatHtml('<div><p>Hello <b>world</b></p><br><img src=a.png></div>')).toBe(
      [
        '<div>',
        '  <p>',
        '    Hello',
        '    <b>',
        '      world',
        '    </b>',
        '  </p>',
        '  <br>',
        '  <img src=a.png>',
        '</div>',
      ].join('\n'),
    );
  });

  it('lays a style block out as CSS and leaves a script and a pre as written', () => {
    const out = formatHtml(
      '<style>a{color:red}</style><script>var a=1;\nvar b=2;</script><pre>x\n  y</pre>',
    );
    expect(out).toContain('  a {');
    expect(out).toContain('    color:red');
    expect(out).toContain('var a=1;\nvar b=2;');
    expect(out).toContain('x\n  y');
  });

  it('keeps comments and the doctype, and copes with odd input', () => {
    expect(formatHtml('<!DOCTYPE html><!-- a\n b --><html></html>')).toBe(
      '<!DOCTYPE html>\n<!-- a b -->\n<html>\n</html>',
    );
    expect(() => formatHtml('</p></div><p')).not.toThrow();
    expect(formatHtml('')).toBe('');
  });

  it('is quick on a long minified page', () => {
    const big = Array.from({ length: 30000 }, (_, i) => `<li class="c${i}">item ${i}</li>`).join(
      '',
    );
    const started = performance.now();
    const out = formatHtml(`<ul>${big}</ul>`);
    expect(out.split('\n').length).toBe(30000 * 3 + 2);
    expect(performance.now() - started).toBeLessThan(3000);
  });
});

describe('locateInHtml', () => {
  const page = [
    '<html><head><title>wheat page</title><style>.wheat{}</style></head>',
    '<body><!-- wheat --><p>The price of <b>wheat</b> &amp; barley rose.</p>',
    '<script>var wheat = 1;</script><p>wheat again</p></body></html>',
  ].join('\n');

  it('finds words through the tags, and not in scripts, styles, comments or the title', () => {
    const found = locateInHtml(page, {
      before: 'The price of ',
      matched: 'wheat',
      after: ' & barley',
    });
    expect(found.line).toBe(2);
    expect(page.slice(found.offset, found.end)).toBe('wheat');
    // The title is text the index keeps (line 1); the comment, the script and the style are not.
    const first = locateInHtml(page, { matched: 'wheat' });
    expect(first.line).toBe(1);
    expect(page.slice(first.offset).startsWith('wheat page')).toBe(true);
    expect(locateInHtml(page, { before: 'price of ', matched: 'wheat' }).line).toBe(2);
    expect(locateInHtml(page, { matched: 'wheat', after: ' again' }).line).toBe(3);
  });

  it('matches across the markup that splits the words, and through entities', () => {
    const found = locateInHtml(page, { matched: 'price of wheat & barley' });
    expect(page.slice(found.offset, found.end)).toBe('price of <b>wheat</b> &amp; barley');
  });

  it('chooses the occurrence whose surroundings match, and says nothing when not found', () => {
    const second = locateInHtml(page, { before: 'again', matched: 'wheat', after: 'again' });
    expect(second.line).toBe(3);
    expect(locateInHtml(page, { before: '', matched: 'wheat', after: ' again' }).line).toBe(3);
    expect(locateInHtml(page, { matched: 'zebra' })).toBeNull();
    expect(locateInHtml('<p>a</p>', { matched: ' ' })).toBeNull();
  });
});
