const $ = (id) => document.getElementById(id);
let current = null;
let dirty = false;
let busy = false;
const DRAFT_KEY = 'csic19.meeting-input.draft.v1';
let pendingDraft = null;

function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); }
  catch { status('無法清除瀏覽器草稿，請檢查瀏覽器儲存設定。', true); return false; }
  pendingDraft = null;
  $('draft-banner').hidden = true;
  return true;
}
function saveDraft() {
  if (!$('keep-draft').checked || !dirty) return;
  // Do not replace an older recoverable draft without an explicit choice.
  if (pendingDraft) return;
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      title: $('title').value, transcript: $('transcript').value,
      current, savedAt: new Date().toISOString(),
    }));
  } catch { status('草稿無法保存在瀏覽器，請手動儲存會議。', true); }
}
function markDirty() { dirty = true; count(); status('尚未儲存'); saveDraft(); }

function status(message, error = false) {
  $('status').textContent = message;
  $('status').dataset.error = String(error);
}
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || '操作失敗，請稍後再試。');
  return body;
}
function count() {
  $('count').textContent = `${$('transcript').value.length.toLocaleString()} / 100,000 字`;
}
function render(meeting) {
  current = meeting;
  $('title').value = meeting?.title || '';
  $('transcript').value = meeting?.transcript || '';
  $('metadata').textContent = meeting ? `最後儲存：${new Date(meeting.updated_at).toLocaleString()} · 版本 ${meeting.revision}` : '';
  $('save').textContent = meeting ? '儲存變更' : '儲存會議';
  dirty = false;
  count();
  document.querySelectorAll('#meetings button').forEach(button => {
    button.setAttribute('aria-current', String(button.dataset.id === meeting?.id));
  });
}
function mayLeave() {
  return !busy && (!dirty || window.confirm('有尚未儲存的內容，確定要離開這份輸入嗎？'));
}
async function loadList() {
  try {
    const { meetings } = await api('/api/meetings');
    $('meetings').replaceChildren();
    $('list-status').textContent = meetings.length ? `${meetings.length} 場會議` : '尚無會議，建立第一份紀錄。';
    for (const meeting of meetings) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.id = meeting.id;
      button.setAttribute('aria-current', String(current?.id === meeting.id));
      const title = document.createElement('span');
      title.textContent = meeting.title;
      const date = document.createElement('small');
      date.textContent = new Date(meeting.updated_at).toLocaleString();
      button.append(title, date);
      button.onclick = async () => {
        if (!mayLeave()) return;
        setBusy(true);
        try {
          const saved = await api(`/api/meetings/${meeting.id}`);
          render(saved);
          status('已載入儲存的內容。');
        } catch (error) { status(error.message, true); }
        finally { setBusy(false); }
      };
      $('meetings').append(button);
    }
  } catch (error) { $('list-status').textContent = `無法載入會議：${error.message}`; }
}
function setBusy(value) {
  busy = value;
  for (const id of ['title', 'transcript', 'save', 'new', 'refresh', 'import-file', 'restore', 'discard', 'keep-draft']) $(id).disabled = value;
}
$('title').addEventListener('input', markDirty);
$('transcript').addEventListener('input', markDirty);
$('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy) return;
  if (!$('title').value.trim() || !$('transcript').value.trim()) return status('標題與會議內容不能只有空白。', true);
  setBusy(true);
  status('正在儲存…');
  try {
    const saved = await api(current ? `/api/meetings/${current.id}` : '/api/meetings', {
      method: current ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({title: $('title').value, transcript: $('transcript').value, ...(current ? {revision: current.revision} : {})}),
    });
    render(saved);
    if (!pendingDraft) clearDraft();
    status('已儲存。');
    await loadList();
  } catch (error) { status(error.message, true); }
  finally { setBusy(false); }
});
$('new').onclick = () => { if (mayLeave()) { render(null); status(''); $('title').focus(); } };
$('refresh').onclick = loadList;
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
$('keep-draft').onchange = () => {
  if ($('keep-draft').checked) saveDraft();
  else if (!clearDraft()) $('keep-draft').checked = true;
};
$('discard').onclick = () => {
  if (window.confirm('確定清除此瀏覽器的草稿？已儲存的會議不受影響。')) clearDraft();
};
$('restore').onclick = () => {
  if (!pendingDraft || !mayLeave()) return;
  const draft = pendingDraft;
  render(draft.current);
  $('title').value = draft.title;
  $('transcript').value = draft.transcript;
  pendingDraft = null;
  $('draft-banner').hidden = true;
  $('keep-draft').checked = true;
  markDirty();
  status('已恢復草稿，請確認內容後儲存。');
};
$('import-file').onchange = async () => {
  const file = $('import-file').files[0];
  if (!file || busy) return;
  setBusy(true);
  try {
    if (!/\.txt$/i.test(file.name)) throw new Error('請選擇 .txt 文字檔。');
    if (file.size > 400000) throw new Error('文字檔不得超過 400 KB。');
    const text = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer());
    if (!text.trim()) throw new Error('文字檔沒有會議內容。');
    if (text.length > 100000) throw new Error('會議內容最多 100,000 字。');
    if (text.includes('\0')) throw new Error('檔案包含非文字資料。');
    if ($('transcript').value && !window.confirm('匯入將取代目前的會議文字，確定繼續？')) return;
    $('transcript').value = text;
    if (!$('title').value.trim()) $('title').value = file.name.replace(/\.txt$/i, '').slice(0, 120);
    markDirty();
    status('已帶入文字檔，請確認內容後儲存。');
  } catch (error) {
    status(error instanceof TypeError ? '無法讀取文字檔，請使用 UTF-8 編碼的 .txt。' : error.message, true);
  } finally { $('import-file').value = ''; setBusy(false); }
};
try {
  const raw = localStorage.getItem(DRAFT_KEY);
  if (raw) {
    const draft = JSON.parse(raw);
    if (typeof draft.title !== 'string' || draft.title.length > 120 ||
        typeof draft.transcript !== 'string' || draft.transcript.length > 100000 ||
        (draft.current !== null && (!draft.current || typeof draft.current.id !== 'string' || !Number.isInteger(draft.current.revision)))) {
      throw new Error('invalid draft');
    }
    pendingDraft = draft;
    $('draft-banner').hidden = false;
  }
} catch { status('瀏覽器草稿無法讀取；你仍可以正常建立與儲存會議。', true); }
loadList();
