// Quick XSS test for AgentChat.renderMarkdown sanitizer
// Run: node tests/test_render_markdown_xss.mjs

const HTML_ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, ch => HTML_ESCAPE[ch] || ch);
function renderMarkdown(text) {
  if (text == null) return '';
  return escapeHtml(String(text))
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br />');
}

const cases = [
  { name: 'script tag escaped',
    input: '<script>alert(1)</script>',
    must:   '&lt;script&gt;',
    forbid: '<script>' },
  { name: 'img onerror escaped',
    input: '<img src=x onerror=alert(1)>',
    must:   '&lt;img',
    forbid: '<img' },
  { name: 'javascript: href escaped',
    input: '<a href="javascript:alert(1)">x</a>',
    must:   '&lt;a href=&quot;javascript:alert(1)&quot;&gt;',
    forbid: '<a href' },
  { name: 'bold still works',
    input: '**hi**',
    must:   '<strong>hi</strong>',
    forbid: '**hi**' },
  { name: 'inline code still works',
    input: 'hello `code`',
    must:   '<code>code</code>',
    forbid: '`code`' },
  { name: 'newline → <br />',
    input: 'a\nb',
    must:   'a<br />b',
    forbid: '\n' },
  { name: 'mixed bold and tag',
    input: '**bold** then <b>x</b>',
    must:   '<strong>bold</strong> then &lt;b&gt;x&lt;/b&gt;',
    forbid: '<b>x</b>' },
];

let pass = 0, fail = 0;
for (const c of cases) {
  const out = renderMarkdown(c.input);
  const ok = out.includes(c.must) && !out.includes(c.forbid);
  if (ok) { pass++; console.log('✅', c.name); }
  else { fail++; console.log('❌', c.name, '\n   got:', out, '\n   need:', c.must, '\n   forbid:', c.forbid); }
}
console.log(`\n${pass}/${cases.length} passed`);
process.exit(fail ? 1 : 0);
