import { describe, expect, it } from 'vitest';
import { JsHighlighter, formatJs } from './js.js';
import { JsonHighlighter, formatJson } from './json.js';
import { XmlHighlighter, formatXml } from './xml.js';
import { TomlHighlighter } from './toml.js';
import { YamlHighlighter } from './yaml.js';
import { locateWords } from './locate.js';

const colour = (Highlighter, lines) => {
  const h = new Highlighter(lines);
  return lines.map((_, i) => h.segments(i));
};
const text = (segments) => segments.map(([, t]) => t).join('');

describe('JSON', () => {
  it('colours keys, strings, numbers and constants', () => {
    const [row] = colour(JsonHighlighter, [
      '  "name": "Ada", "age": -3.5e2, "ok": true, "x": null, "l": [1]',
    ]);
    expect(row).toContainEqual(['key', '"name"']);
    expect(row).toContainEqual(['string', '"Ada"']);
    expect(row).toContainEqual(['number', '-3.5e2']);
    expect(row).toContainEqual(['constant', 'true']);
    expect(row).toContainEqual(['constant', 'null']);
    expect(text(row)).toBe('  "name": "Ada", "age": -3.5e2, "ok": true, "x": null, "l": [1]');
  });

  it('keeps any line whole, even a broken one', () => {
    for (const line of ['{"a": "unterminated', '}}]]', '"\\"", "\\\\"', '', 'nul tru -']) {
      expect(text(colour(JsonHighlighter, [line])[0])).toBe(line);
    }
  });

  it('lays a minified file out, exactly as written', () => {
    const minified =
      '{"a":[1,2,{"b":null}],"e":{},"l":[],"s":"x,y:{z}","a":9007199254740993,"1":2}';
    expect(formatJson(minified)).toBe(
      [
        '{',
        '  "a": [',
        '    1,',
        '    2,',
        '    {',
        '      "b": null',
        '    }',
        '  ],',
        '  "e": {},',
        '  "l": [],',
        '  "s": "x,y:{z}",',
        '  "a": 9007199254740993,',
        '  "1": 2',
        '}',
      ].join('\n'),
    );
    expect(() => formatJson('}}{[')).not.toThrow();
    expect(formatJson('')).toBe('');
  });

  it('is quick on a long minified file', () => {
    const big = `[${Array.from({ length: 80000 }, (_, i) => `{"id":${i},"v":"x"}`).join(',')}]`;
    const started = performance.now();
    expect(formatJson(big).split('\n').length).toBe(80000 * 4 + 2);
    expect(performance.now() - started).toBeLessThan(3000);
  });
});

describe('YAML', () => {
  const doc = [
    '# settings',
    '---',
    'server:',
    '  host: "localhost"   # where',
    '  ports: [8080, 8081]',
    '  debug: yes',
    '  ratio: 0.5',
    'items:',
    '  - name: a',
    '    tags: &t [x, y]',
    '  - *t',
    'text: |',
    '  line one',
    '  key: not a key',
    '',
    '  line two',
    'after: done',
  ];
  const rows = colour(YamlHighlighter, doc);

  it('colours comments, keys, strings, numbers, constants and anchors', () => {
    expect(rows[0]).toEqual([['comment', '# settings']]);
    expect(rows[1][0]).toEqual(['punct', '---']);
    expect(rows[3]).toContainEqual(['key', 'host']);
    expect(rows[3]).toContainEqual(['string', '"localhost"']);
    expect(rows[3]).toContainEqual(['comment', '# where']);
    expect(rows[4]).toContainEqual(['number', '8080']);
    expect(rows[5]).toContainEqual(['constant', 'yes']);
    expect(rows[6]).toContainEqual(['number', '0.5']);
    expect(rows[8]).toContainEqual(['key', 'name']);
    expect(rows[9]).toContainEqual(['function', '&t']);
    expect(rows[10]).toContainEqual(['function', '*t']);
  });

  it('carries a block scalar over its lines (blank ones too) and ends it', () => {
    expect(rows[11]).toContainEqual(['function', '|']);
    expect(rows[12]).toEqual([['string', '  line one']]);
    expect(rows[13]).toEqual([['string', '  key: not a key']]);
    expect(rows[14]).toEqual([['string', '']].filter(([, t]) => t));
    expect(rows[15]).toEqual([['string', '  line two']]);
    expect(rows[16]).toContainEqual(['key', 'after']);
  });

  it('keeps every line whole and copes with odd input', () => {
    for (const line of doc) expect(text(colour(YamlHighlighter, [line])[0])).toBe(line);
    expect(() =>
      colour(YamlHighlighter, ['- - - x', ': :', '"', "'a", '? k', '{[', '|', '>-']),
    ).not.toThrow();
    const lines = Array.from({ length: 20000 }, (_, i) =>
      i === 7000 ? 'k: |' : i > 7000 && i < 7010 ? '  body' : 'a: 1',
    );
    expect(new YamlHighlighter(lines).segments(7005)).toEqual([['string', '  body']]);
  });
});

describe('TOML', () => {
  const doc = [
    '# project',
    '[package]',
    'name = "vethuq"  # the name',
    "version = '1.2.0'",
    'build = 42',
    'ratio = -3.5e2',
    'public = true',
    'released = 2026-10-14T10:00:00Z',
    'authors = ["Ada", "Grace"]',
    'point = { x = 1, y = 2 }',
    '[[bin]]',
    'a.b."c d" = 0x1F',
    'text = \"\"\"',
    'line one [not.a.header]',
    'key = "not a key"',
    '\"\"\" # done',
    "raw = '''",
    'still raw \"\"\"',
    "''' ",
    'after = 1',
  ];
  const rows = colour(TomlHighlighter, doc);

  it('colours comments, tables, keys, strings, numbers, dates and constants', () => {
    expect(rows[0]).toEqual([['comment', '# project']]);
    expect(rows[1]).toEqual([['function', '[package]']]);
    expect(rows[2]).toContainEqual(['key', 'name']);
    expect(rows[2]).toContainEqual(['string', '"vethuq"']);
    expect(rows[2]).toContainEqual(['comment', '# the name']);
    expect(rows[3]).toContainEqual(['string', "'1.2.0'"]);
    expect(rows[4]).toContainEqual(['number', '42']);
    expect(rows[5]).toContainEqual(['number', '-3.5e2']);
    expect(rows[6]).toContainEqual(['constant', 'true']);
    expect(rows[7]).toContainEqual(['number', '2026-10-14T10:00:00Z']);
    expect(rows[8]).toContainEqual(['string', '"Ada"']);
    expect(rows[9]).toContainEqual(['key', 'x']);
    expect(rows[10]).toEqual([['function', '[[bin]]']]);
    expect(rows[11]).toContainEqual(['key', 'a.b."c d"']);
    expect(rows[11]).toContainEqual(['number', '0x1F']);
  });

  it('carries a multi-line string over its lines and ends it', () => {
    expect(rows[12]).toContainEqual(['string', '\"\"\"']);
    expect(rows[13]).toEqual([['string', 'line one [not.a.header]']]);
    expect(rows[14]).toEqual([['string', 'key = "not a key"']]);
    expect(rows[15]).toContainEqual(['string', '\"\"\"']);
    expect(rows[15]).toContainEqual(['comment', '# done']);
    expect(rows[17]).toEqual([['string', 'still raw \"\"\"']]);
    expect(rows[19]).toContainEqual(['key', 'after']);
  });

  it('keeps every line whole and copes with odd input', () => {
    for (const line of doc) expect(text(colour(TomlHighlighter, [line])[0])).toBe(line);
    for (const line of ['= =', '[', ']]', '"', "'a", '{[', '\"\"\"', 'a = ,,', '[[]]=', '#']) {
      expect(text(colour(TomlHighlighter, [line])[0])).toBe(line);
    }
    const lines = Array.from({ length: 20000 }, (_, i) =>
      i === 7000 ? 'k = \"\"\"' : i > 7000 && i < 7010 ? 'body' : 'a = 1',
    );
    expect(new TomlHighlighter(lines).segments(7005)).toEqual([['string', 'body']]);
  });
});

describe('JavaScript', () => {
  const [row] = colour(JsHighlighter, [
    'export const total = items.map((x) => x * 2.5).filter(Boolean); // sum',
  ]);

  it('colours keywords, storage, functions, members, numbers, comments', () => {
    expect(row).toContainEqual(['keyword', 'export']);
    expect(row).toContainEqual(['storage', 'const']);
    expect(row).toContainEqual(['identifier', 'total']);
    expect(row).toContainEqual(['function', 'map']);
    expect(row).toContainEqual(['function', 'filter']);
    expect(colour(JsHighlighter, ['a.length + b.c'])[0]).toContainEqual(['member', 'length']);
    expect(row).toContainEqual(['number', '2.5']);
    expect(row).toContainEqual(['comment', '// sum']);
  });

  it('knows a function call, a string, a regex and a division', () => {
    const r = colour(JsHighlighter, [
      'run("a\\"b", `t`); const re = /ab+[/]c/gi; const q = a / b / c; return x /y/ 2;',
    ])[0];
    expect(r).toContainEqual(['function', 'run']);
    expect(r).toContainEqual(['string', '"a\\"b"']);
    expect(r).toContainEqual(['regexp', '/ab+[/]c/gi']);
    expect(r.filter(([k]) => k === 'regexp')).toHaveLength(1);
  });

  it('carries a block comment and a template literal over lines, with expressions inside', () => {
    const r = colour(JsHighlighter, [
      '/* one',
      ' two */ let a = `text ${ f({ k: 1 }) } more',
      'still template ${b} end`; let z = 1;',
    ]);
    expect(r[1][0]).toEqual(['comment', ' two */']);
    expect(r[1]).toContainEqual(['storage', 'let']);
    expect(r[1]).toContainEqual(['function', 'f']);
    expect(r[1].some(([k, t]) => k === 'string' && t.endsWith(' more'))).toBe(true);
    expect(r[2][0][0]).toBe('string');
    expect(r[2]).toContainEqual(['identifier', 'b']);
    expect(r[2]).toContainEqual(['storage', 'let']);
    expect(r[2]).toContainEqual(['number', '1']);
  });

  it('keeps every line whole', () => {
    for (const line of [
      '#!/usr/bin/env node',
      'a ? b : c',
      '`unterminated ${',
      '}}}',
      '/',
      '/*',
      '0x1F + 1_000n + .5e-3',
      '"x',
      '',
    ]) {
      expect(text(colour(JsHighlighter, [line])[0])).toBe(line);
    }
  });

  it('lays a minified script out roughly', () => {
    const out = formatJs(
      'function f(a,b){if(a){return b}else{for(let i=0;i<3;i++){g(`x;${i}`,"a;b",/;/)}}}f(1,2);',
    );
    expect(out).toBe(
      [
        'function f(a,b) {',
        '  if(a) {',
        '    return b',
        '  } else {',
        '    for(let i=0;i<3;i++) {',
        '      g(`x;${i}`,"a;b",/;/)',
        '    }',
        '  }',
        '}',
        'f(1,2);',
      ].join('\n'),
    );
    expect(formatJs('/* a;b */ x=1; // c;d\ny=2;')).toBe('/* a;b */\nx=1;\n// c;d\ny=2;');
    expect(() => formatJs('}}} ( ` /*')).not.toThrow();
  });

  it('is quick on a long minified bundle', () => {
    const big = Array.from({ length: 40000 }, (_, i) => `function f${i}(a){return a+${i};}`).join(
      '',
    );
    const started = performance.now();
    expect(formatJs(big).split('\n').length).toBe(40000 * 3);
    expect(performance.now() - started).toBeLessThan(3000);
  });
});

describe('XML', () => {
  const doc = [
    '<?xml version="1.0"?>',
    '<!-- a',
    ' note -->',
    '<ns:catalog xmlns:ns="u" lang=\'en\'>',
    '  <book id="7">Dune &amp; more</book>',
    '  <![CDATA[ <raw> ]]>',
    '  <br/>',
    '</ns:catalog>',
  ];
  const rows = colour(XmlHighlighter, doc);

  it('colours tags, attributes, values, entities, comments, CDATA and instructions', () => {
    expect(rows[0].every(([k]) => k === 'doctype')).toBe(true);
    expect(rows[2]).toEqual([['comment', ' note -->']]);
    expect(rows[3]).toContainEqual(['tag', 'ns:catalog']);
    expect(rows[3]).toContainEqual(['attribute', 'xmlns:ns']);
    expect(rows[3]).toContainEqual(['attrvalue', '"u"']);
    expect(rows[3]).toContainEqual(['attrvalue', "'en'"]);
    expect(rows[4]).toContainEqual(['entity', '&amp;']);
    expect(rows[4]).toContainEqual(['attribute', 'id']);
    expect(rows[5].some(([k, t]) => k === null && t.includes('<raw>'))).toBe(true);
    expect(rows[7]).toContainEqual(['tag', 'ns:catalog']);
  });

  it('keeps every line whole', () => {
    for (const line of doc) expect(text(colour(XmlHighlighter, [line])[0])).toBe(line);
    expect(() =>
      colour(XmlHighlighter, ['<', '</', '<a', '<!', '<?', '>>', '<![CDATA[']),
    ).not.toThrow();
  });

  it('lays a document out, keeping text-only elements on a line', () => {
    expect(
      formatXml(
        '<?xml version="1.0"?><catalog><book id="7"><title>Dune</title><empty/></book><!-- c --></catalog>',
      ),
    ).toBe(
      [
        '<?xml version="1.0"?>',
        '<catalog>',
        '  <book id="7">',
        '    <title>Dune</title>',
        '    <empty/>',
        '  </book>',
        '  <!-- c -->',
        '</catalog>',
      ].join('\n'),
    );
    expect(() => formatXml('</a><b')).not.toThrow();
    expect(formatXml('')).toBe('');
  });

  it('is quick on a long document', () => {
    const big = `<r>${Array.from({ length: 40000 }, (_, i) => `<i n="${i}">v</i>`).join('')}</r>`;
    const started = performance.now();
    expect(formatXml(big).split('\n').length).toBe(40002);
    expect(performance.now() - started).toBeLessThan(3000);
  });
});

describe('locateWords with a hint', () => {
  it('prefers the occurrence after the key, for a file indexed as key: value lines', () => {
    const json = '{"a": {"port": 80}, "b": {"ports": [8080]}, "c": {"port": 8080}}';
    const plain = locateWords(json, { matched: '8080' });
    expect(plain.offset).toBe(json.indexOf('8080'));
    const hinted = locateWords(json, { matched: '8080', hint: '"port"' });
    expect(hinted.offset).toBe(json.lastIndexOf('8080'));
    expect(locateWords(json, { matched: '8080', hint: 'nowhere' }).offset).toBe(plain.offset);
  });
});
