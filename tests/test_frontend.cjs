// Exercise browser event handlers without external dependencies.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function browser(draft) {
  const elements = new Map();
  const storage = new Map(draft ? [['csic19.meeting-input.draft.v1', JSON.stringify(draft)]] : []);
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, hidden: true, dataset: {}, textContent: '', files: [],
      addEventListener(name, fn) { this[name] = fn; },
      setAttribute() {}, replaceChildren() {}, append() {}, focus() {},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => [], createElement: () => element(Symbol())},
    window: {confirm: () => true, addEventListener() {}},
    localStorage: {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)},
    fetch: async () => ({ok: true, json: async () => ({meetings: []})}),
    TextDecoder, Date, console,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8'), context);
  return {element, storage, context};
}
function file(name, text) {
  return {name, size: Buffer.byteLength(text), arrayBuffer: async () => new TextEncoder().encode(text).buffer};
}

test('UTF-8 import fills title and transcript without auto-saving', async () => {
  const {element: e} = browser();
  e('import-file').files = [file('分工.txt', '小明：週五完成。\n小華：收到。')];
  await e('import-file').onchange();
  assert.equal(e('title').value, '分工');
  assert.equal(e('transcript').value, '小明：週五完成。\n小華：收到。');
  assert.match(e('status').textContent, /請確認/);
  assert.equal(e('save').disabled, false);
});
test('invalid or oversized import preserves existing input', async () => {
  const {element: e} = browser();
  e('transcript').value = '原文';
  for (const upload of [file('bad.csv', '內容'), file('empty.txt', '  '), file('long.txt', 'a'.repeat(100001)),
    {name: 'bad.txt', size: 1, arrayBuffer: async () => new Uint8Array([255]).buffer}]) {
    e('import-file').files = [upload];
    await e('import-file').onchange();
    assert.equal(e('transcript').value, '原文');
    assert.equal(e('status').dataset.error, 'true');
  }
});
test('cancel import keeps existing text', async () => {
  const {element: e, context} = browser();
  e('transcript').value = '原文';
  context.window.confirm = () => false;
  e('import-file').files = [file('new.txt', '新文')];
  await e('import-file').onchange();
  assert.equal(e('transcript').value, '原文');
});
test('draft storage is opt-in and can be cleared', () => {
  const {element: e, storage} = browser();
  e('title').value = '草稿';
  e('title').input();
  assert.equal(storage.size, 0);
  e('keep-draft').checked = true;
  e('keep-draft').onchange();
  assert.equal(storage.size, 1);
  e('keep-draft').checked = false;
  e('keep-draft').onchange();
  assert.equal(storage.size, 0);
});
test('restore retains original revision for conflict detection', () => {
  const {element: e, storage} = browser({title: '未完成', transcript: '內容', current: {id: 'meeting-id', revision: 3}});
  assert.equal(e('draft-banner').hidden, false);
  e('restore').onclick();
  assert.equal(e('title').value, '未完成');
  assert.equal(e('transcript').value, '內容');
  assert.equal(JSON.parse([...storage.values()][0]).current.revision, 3);
  assert.equal(e('keep-draft').checked, true);
});
test('storage failure keeps form input available', () => {
  const {element: e, context} = browser();
  context.localStorage.setItem = () => {throw new Error('quota');};
  e('title').value = '不可遺失';
  e('keep-draft').checked = true;
  e('title').input();
  assert.equal(e('title').value, '不可遺失');
  assert.equal(e('status').dataset.error, 'true');
});
