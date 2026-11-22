// Exercise browser event handlers without external dependencies.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function browser(draft, storage = new Map(draft ? [['csic19.meeting-input.draft.v1', JSON.stringify(draft)]] : [])) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, hidden: true, dataset: {}, textContent: '', files: [],
      addEventListener(name, fn) { this[name] = fn; },
      setAttribute() {}, replaceChildren() {}, append() {}, focus() {}, click() {}, remove() {},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => [], createElement: () => element(Symbol()), body: {append() {}}},
    window: {confirm: () => true, addEventListener() {}},
    localStorage: {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)},
    fetch: async () => ({ok: true, json: async () => ({meetings: []})}),
    TextDecoder, Date, console, Blob, URL, setTimeout: fn => fn(),
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
  assert.deepEqual([...storage.keys()], ['csic19.draft.meeting-id']);
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

function existingMeeting() {
  const meeting = {id: 'original', revision: 1, title: '原標題', transcript: '原文'};
  const setup = browser({title: '我的標題', transcript: '我的未儲存文字', current: meeting});
  setup.element('restore').onclick();
  return setup;
}
test('409 exposes recovery without discarding local text or stale revision', async () => {
  const {element: e, context} = existingMeeting();
  context.fetch = async () => ({ok: false, status: 409, json: async () => ({error: '版本衝突'})});
  await e('form').submit({preventDefault() {}});
  assert.equal(e('conflict-panel').hidden, false);
  assert.equal(e('transcript').value, '我的未儲存文字');
  assert.equal(e('save-copy').disabled, false);
});
test('save copy posts a new record without revision and switches to it', async () => {
  const {element: e, context} = existingMeeting();
  e('title').value = '字'.repeat(120);
  let payload;
  context.fetch = async (url, options) => {
    if (!options) return {ok: true, json: async () => ({meetings: []})};
    assert.equal(url, '/api/meetings');
    assert.equal(options.method, 'POST');
    payload = JSON.parse(options.body);
    return {ok: true, json: async () => ({...payload, id: 'copy', revision: 1})};
  };
  await e('save-copy').onclick();
  assert.equal(payload.transcript, '我的未儲存文字');
  assert.equal(payload.title, '字'.repeat(113) + ' (衝突備份)');
  assert.equal('revision' in payload, false);
  assert.equal(e('conflict-panel').hidden, true);
  assert.match(e('status').textContent, /另存/);
});
test('shared storage isolates two meetings and a new draft', () => {
  const first = browser();
  const second = browser(null, first.storage);
  const edit = (tab, id, title) => {
    vm.runInContext(id ? `render({id: '${id}', revision: 1})` : 'render(null)', tab.context);
    tab.element('keep-draft').checked = true;
    tab.element('title').value = title;
    tab.element('title').input();
  };
  edit(first, 'one', '第一場');
  edit(second, 'two', '第二場');
  edit(second, null, '新會議');
  vm.runInContext("render({id: 'one', revision: 2})", second.context);
  second.element('restore').onclick();
  assert.equal(second.element('title').value, '第一場');
  assert.equal(vm.runInContext('current.revision', second.context), 1);
  second.element('discard').onclick();
  assert.deepEqual([...first.storage.keys()], ['csic19.draft.two', 'csic19.draft.new']);
});
test('delete confirms, sends the visible revision and preserves input on conflict', async () => {
  const {element: e, context, storage} = existingMeeting();
  let requests = 0;
  let conflict = true;
  context.fetch = async (url, options) => {
    if (!options) return {ok: true, json: async () => ({meetings: []})};
    requests++;
    assert.equal(url, '/api/meetings/original');
    assert.equal(options.method, 'DELETE');
    assert.deepEqual(JSON.parse(options.body), {revision: 1});
    return conflict
      ? {ok: false, status: 409, json: async () => ({error: '版本衝突'})}
      : {ok: true, json: async () => ({id: 'original'})};
  };
  context.window.confirm = () => false;
  await e('delete').onclick();
  assert.equal(requests, 0);
  context.window.confirm = () => true;
  await e('delete').onclick();
  assert.equal(e('transcript').value, '我的未儲存文字');
  assert.equal(storage.size, 1);
  conflict = false;
  await e('delete').onclick();
  assert.equal(requests, 2);
  assert.equal(e('delete').hidden, true);
  assert.equal(e('transcript').value, '');
  assert.equal(storage.size, 0);
});
test('cancel or failed latest reload preserves local input', async () => {
  const {element: e, context} = existingMeeting();
  context.window.confirm = () => false;
  await e('reload-latest').onclick();
  assert.equal(e('transcript').value, '我的未儲存文字');
  context.window.confirm = () => true;
  context.fetch = async () => {throw new Error('offline');};
  await e('reload-latest').onclick();
  assert.equal(e('transcript').value, '我的未儲存文字');
  assert.equal(e('status').dataset.error, 'true');
});
test('confirmed reload replaces input and clears recovered draft', async () => {
  const {element: e, context, storage} = existingMeeting();
  context.fetch = async () => ({ok: true, json: async () => ({id: 'original', revision: 2, title: '最新', transcript: '新版'})});
  await e('reload-latest').onclick();
  assert.equal(e('transcript').value, '新版');
  assert.equal(storage.size, 0);
});
test('download preserves unsaved text and exports UTF-8 text only', async () => {
  const {element: e, context} = existingMeeting();
  let blob, anchor, revoked;
  context.URL = {createObjectURL: value => {blob = value; return 'blob:test';}, revokeObjectURL: value => {revoked = value;}};
  context.document.createElement = () => (anchor = {click() {}, remove() {}});
  e('title').value = 'a/b';
  e('download').onclick();
  assert.equal(await blob.text(), '我的未儲存文字');
  assert.equal(anchor.download, 'a_b.txt');
  assert.equal(revoked, 'blob:test');
  assert.equal(e('transcript').value, '我的未儲存文字');
});
