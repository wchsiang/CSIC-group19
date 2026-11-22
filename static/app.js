const $ = (id) => document.getElementById(id);
let current = null;
let dirty = false;
let busy = false;
const LEGACY_DRAFT_KEY = 'csic19.meeting-input.draft.v1';
const LLM_SETTINGS_KEY = 'csic19.llm.settings.v1';
let pendingDraft = null;
let storedDraft = null;

function draftKey() { return `csic19.draft.${current?.id ?? 'new'}`; }
function readDraft(recoverLegacy = false) {
  pendingDraft = null;
  storedDraft = null;
  $('draft-banner').hidden = true;
  $('keep-draft').checked = false;
  try {
    const key = draftKey();
    let source = key;
    let raw = localStorage.getItem(key);
    if (raw === null) {
      source = LEGACY_DRAFT_KEY;
      raw = localStorage.getItem(source);
    }
    if (raw === null) return;
    const draft = JSON.parse(raw);
    if (!draft || typeof draft.title !== 'string' || draft.title.length > 120 ||
        typeof draft.transcript !== 'string' || draft.transcript.length > 100000 ||
        (draft.current !== null && (!draft.current || typeof draft.current.id !== 'string' ||
          !Number.isInteger(draft.current.revision) || draft.current.revision < 1))) {
      throw new Error('invalid draft');
    }
    if (draft.current?.id !== current?.id) {
      if (recoverLegacy && source === LEGACY_DRAFT_KEY && draft.current) render(draft.current);
      return;
    }
    storedDraft = {key: source, raw};
    pendingDraft = draft;
    $('draft-banner').hidden = false;
  } catch { status('瀏覽器草稿無法讀取；你仍可以正常建立與儲存會議。', true); }
}
function clearDraft() {
  try {
    if (storedDraft && localStorage.getItem(storedDraft.key) === storedDraft.raw) {
      localStorage.removeItem(storedDraft.key);
    }
  }
  catch { status('無法清除瀏覽器草稿，請檢查瀏覽器儲存設定。', true); return false; }
  storedDraft = null;
  pendingDraft = null;
  $('draft-banner').hidden = true;
  return true;
}
function saveDraft() {
  if (!$('keep-draft').checked || !dirty) return;
  if (pendingDraft) return;
  try {
    const key = draftKey();
    const previous = storedDraft?.key === key ? storedDraft.raw : null;
    if (localStorage.getItem(key) !== previous) {
      status('另一個分頁已變更這份草稿。目前輸入仍在表單中，可下載或儲存會議。', true);
      return;
    }
    const raw = JSON.stringify({
      title: $('title').value, transcript: $('transcript').value,
      current: current ? {id: current.id, revision: current.revision} : null,
    });
    localStorage.setItem(key, raw);
    if (storedDraft?.key === LEGACY_DRAFT_KEY && localStorage.getItem(LEGACY_DRAFT_KEY) === storedDraft.raw) {
      localStorage.removeItem(LEGACY_DRAFT_KEY);
    }
    storedDraft = {key, raw};
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
  if (!response.ok) {
    const error = new Error(body.error || '操作失敗，請稍後再試。');
    error.status = response.status;
    throw error;
  }
  return body;
}
function count() {
  $('count').textContent = `${$('transcript').value.length.toLocaleString()} / 100,000 字`;
}
function render(meeting) {
  $('conflict-panel').hidden = true;
  current = meeting;
  $('title').value = meeting?.title || '';
  $('transcript').value = meeting?.transcript || '';
  $('metadata').textContent = meeting ? `最後儲存：${new Date(meeting.updated_at).toLocaleString()} · 版本 ${meeting.revision}` : '';
  $('save').textContent = meeting ? '儲存變更' : '儲存會議';
  $('delete').hidden = !meeting;
  dirty = false;
  count();
  document.querySelectorAll('#meetings button').forEach(button => {
    button.setAttribute('aria-current', String(button.dataset.id === meeting?.id));
  });
  readDraft();

  if (meeting) {
    $('summary-section').hidden = false;
    loadSummary(meeting.id);
  } else {
    $('summary-section').hidden = true;
  }
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
  for (const id of ['title', 'transcript', 'save', 'delete', 'new', 'refresh', 'import-file', 'restore', 'discard', 'keep-draft', 'save-copy', 'reload-latest', 'download', 'generate-summary', 'open-settings']) {
    const el = $(id);
    if (el) el.disabled = value;
  }
}
$('title').addEventListener('input', markDirty);
$('transcript').addEventListener('input', markDirty);
async function saveMeeting(asCopy = false) {
  if (busy) return;
  if (!$('title').value.trim() || !$('transcript').value.trim()) return status('標題與會議內容不能只有空白。', true);
  setBusy(true);
  status('正在儲存…');
  try {
    const updating = current && !asCopy;
    const suffix = ' (衝突備份)';
    const inputTitle = $('title').value.trim();
    const title = asCopy ? Array.from(inputTitle).slice(0, 120 - suffix.length).join('').trimEnd() + suffix : inputTitle;
    const saved = await api(updating ? `/api/meetings/${current.id}` : '/api/meetings', {
      method: updating ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({title, transcript: $('transcript').value, ...(updating ? {revision: current.revision} : {})}),
    });
    const cleared = pendingDraft || clearDraft();
    render(saved);
    if (cleared) status(asCopy ? '已另存為新會議，原會議未被修改。' : '已儲存。');
    await loadList();
  } catch (error) {
    if (current && !asCopy && (error.status === 409 || error.status === 404)) {
      $('conflict-panel').hidden = false;
      $('reload-latest').hidden = error.status === 404;
    }
    status(error.message, true);
  }
  finally { setBusy(false); }
}
$('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  await saveMeeting();
});
$('save-copy').onclick = () => saveMeeting(true);
$('delete').onclick = async () => {
  if (busy || !current) return;
  if (!window.confirm(`確定永久刪除「${current.title}」？目前未儲存的輸入與此會議的瀏覽器草稿也會清除。`)) return;
  setBusy(true);
  try {
    await api(`/api/meetings/${current.id}`, {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({revision: current.revision}),
    });
    const cleared = clearDraft();
    render(null);
    if (cleared) status('已刪除會議。');
    await loadList();
    $('title').focus();
  } catch (error) {
    status(error.message, true);
    if (error.status === 404 || error.status === 409) await loadList();
  } finally { setBusy(false); }
};
$('reload-latest').onclick = async () => {
  if (busy || !current || !window.confirm('確定捨棄目前輸入並載入最新版？建議先下載文字備份。')) return;
  setBusy(true);
  try {
    const latest = await api(`/api/meetings/${current.id}`);
    const cleared = pendingDraft || clearDraft();
    render(latest);
    if (cleared) status('已載入最新版。');
  } catch (error) { status(error.message, true); }
  finally { setBusy(false); }
};
$('download').onclick = () => {
  if (busy) return;
  if (!$('transcript').value.trim()) return status('請先輸入要備份的會議文字。', true);
  const title = $('title').value.trim() || '會議原文';
  const filename = title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').slice(0, 80);
  const content = `會議標題：${title}\n匯出時間：${new Date().toLocaleString()}\n--------------------\n\n${$('transcript').value}`;
  const url = URL.createObjectURL(new Blob(['\ufeff', content], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  status('已請求下載目前文字，請確認瀏覽器下載結果；此操作不會儲存到會議資料庫。');
};
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
  if (current) current = {...current, revision: draft.current.revision};
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

// Module B: LLM Settings & Summary Management
function getLLMSettings() {
  try {
    const raw = localStorage.getItem(LLM_SETTINGS_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return { provider: 'gemini', api_key: '', model: '' };
}
function saveLLMSettings(settings) {
  try {
    localStorage.setItem(LLM_SETTINGS_KEY, JSON.stringify(settings));
    return true;
  } catch { return false; }
}

const PROVIDER_INFO = {
  gemini: {
    link: 'https://aistudio.google.com/apikey',
    linkText: '👉 免費取得 Gemini 金鑰',
    keyPlaceholder: '貼上你的 Gemini API Key (AIza...)',
    modelPlaceholder: '例如：gemini-3.5-flash',
  },
  claude: {
    link: 'https://console.anthropic.com/settings/keys',
    linkText: '👉 取得 Claude 金鑰 (Anthropic Console)',
    keyPlaceholder: '貼上你的 Claude API Key (sk-ant-...)',
    modelPlaceholder: '例如：claude-3-5-haiku-20241022',
  },
  openai: {
    link: 'https://platform.openai.com/api-keys',
    linkText: '👉 取得 OpenAI 金鑰 (OpenAI Platform)',
    keyPlaceholder: '貼上你的 OpenAI API Key (sk-...)',
    modelPlaceholder: '例如：gpt-4o-mini',
  },
  heuristic: {
    link: '#',
    linkText: '（離線規則抽取無需金鑰）',
    keyPlaceholder: '無需輸入金鑰',
    modelPlaceholder: '本機規則引擎',
  }
};

function updateProviderUI(provider) {
  const info = PROVIDER_INFO[provider] || PROVIDER_INFO.gemini;
  $('get-key-link').href = info.link;
  $('get-key-link').textContent = info.linkText;
  $('api-key-input').placeholder = info.keyPlaceholder;
  $('model-input').placeholder = info.modelPlaceholder;
  $('key-container').hidden = (provider === 'heuristic');
}

$('open-settings').onclick = () => {
  const settings = getLLMSettings();
  $('provider-select').value = settings.provider || 'gemini';
  $('api-key-input').value = settings.api_key || '';
  $('model-input').value = settings.model || '';
  updateProviderUI(settings.provider || 'gemini');
  $('test-status').textContent = '';
  $('settings-dialog').showModal();
};

$('close-settings').onclick = () => $('settings-dialog').close();

$('provider-select').onchange = () => {
  updateProviderUI($('provider-select').value);
  $('test-status').textContent = '';
};

$('toggle-key-visibility').onclick = () => {
  const input = $('api-key-input');
  input.type = input.type === 'password' ? 'text' : 'password';
};

$('test-key-btn').onclick = async () => {
  const provider = $('provider-select').value;
  const api_key = $('api-key-input').value.trim();
  const model = $('model-input').value.trim();
  if (provider === 'heuristic') {
    $('test-status').textContent = '✅ 本機離線規則抽取隨時可用，無需連線。';
    $('test-status').dataset.error = 'false';
    return;
  }
  if (!api_key) {
    $('test-status').textContent = '請先填入 API Key 再測試連線。';
    $('test-status').dataset.error = 'true';
    return;
  }
  $('test-status').textContent = '正在測試連線中…';
  $('test-status').dataset.error = 'false';
  try {
    const res = await api('/api/test-llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key, model })
    });
    $('test-status').textContent = `✅ ${res.message}`;
    $('test-status').dataset.error = 'false';
  } catch (err) {
    $('test-status').textContent = `❌ ${err.message}`;
    $('test-status').dataset.error = 'true';
  }
};

$('save-settings-btn').onclick = (e) => {
  e.preventDefault();
  const provider = $('provider-select').value;
  const api_key = $('api-key-input').value.trim();
  const model = $('model-input').value.trim();
  saveLLMSettings({ provider, api_key, model });
  $('settings-dialog').close();
  status(`已儲存 AI 模型設定（${provider}）。`);
};

$('clear-settings-btn').onclick = () => {
  if (window.confirm('確定清除已儲存的 API Key？')) {
    saveLLMSettings({ provider: 'gemini', api_key: '', model: '' });
    $('api-key-input').value = '';
    $('model-input').value = '';
    $('test-status').textContent = '已清除金鑰。';
  }
};

async function loadSummary(meetingId) {
  try {
    const data = await api(`/api/meetings/${meetingId}/summary`);
    renderSummary(data);
  } catch (error) {
    if (error.status === 404) {
      $('summary-content').hidden = true;
      $('no-summary-hint').hidden = false;
      $('stale-warning').hidden = true;
      $('summary-badge').textContent = '尚未產生';
      $('summary-badge').className = 'badge';
      $('summary-provider').textContent = '';
      $('generate-summary').textContent = '✨ 產生 AI 摘要與待辦';
    } else {
      status(`無法載入 AI 摘要：${error.message}`, true);
    }
  }
}

function renderSummary(data) {
  $('summary-content').hidden = false;
  $('no-summary-hint').hidden = true;
  $('summary-text').textContent = data.summary;

  $('decisions-list').replaceChildren();
  if (data.decisions && data.decisions.length > 0) {
    for (const dec of data.decisions) {
      const li = document.createElement('li');
      li.textContent = dec;
      $('decisions-list').append(li);
    }
  } else {
    const li = document.createElement('li');
    li.textContent = '本次會議無明確共識決策紀錄。';
    li.className = 'hint';
    $('decisions-list').append(li);
  }

  $('action-items-body').replaceChildren();
  if (data.action_items && data.action_items.length > 0) {
    for (const item of data.action_items) {
      const tr = document.createElement('tr');
      const tdAssignee = document.createElement('td');
      tdAssignee.textContent = item.assignee || '未指派';
      const tdTask = document.createElement('td');
      tdTask.textContent = item.task;
      const tdDue = document.createElement('td');
      tdDue.textContent = item.due || '未指定期限';
      tr.append(tdAssignee, tdTask, tdDue);
      $('action-items-body').append(tr);
    }
  } else {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 3;
    td.textContent = '無待辦事項紀錄。';
    td.className = 'hint';
    tr.append(td);
    $('action-items-body').append(tr);
  }

  if (data.is_stale) {
    $('stale-warning').hidden = false;
    $('stale-src-rev').textContent = data.source_revision;
    $('stale-curr-rev').textContent = current?.revision || data.source_revision;
    $('summary-badge').textContent = '⚠️ 摘要待更新';
    $('summary-badge').className = 'badge badge-warning';
  } else {
    $('stale-warning').hidden = true;
    $('summary-badge').textContent = `已同步 (v${data.source_revision})`;
    $('summary-badge').className = 'badge badge-success';
  }

  $('summary-provider').textContent = data.provider ? `✨ 由 ${data.provider} 整理` : '';
  $('summary-meta').textContent = `最後整理時間：${new Date(data.updated_at).toLocaleString()}`;
  $('generate-summary').textContent = '🔄 重新產生摘要';
}

$('generate-summary').onclick = async () => {
  if (busy || !current) return;
  if (dirty && !window.confirm('目前會議內容有尚未儲存的變更。產生摘要將使用已儲存的內容，是否繼續？')) return;
  setBusy(true);

  const settings = getLLMSettings();
  const providerLabel = settings.provider === 'claude' ? 'Claude' : (settings.provider === 'gemini' ? 'Gemini' : (settings.provider === 'openai' ? 'OpenAI' : '本機離線規則'));
  status(`正在透過 ${providerLabel} 分析並整理會議逐字稿…`);

  try {
    const payload = (settings.provider !== 'heuristic' && settings.api_key) ? {
      provider: settings.provider,
      api_key: settings.api_key,
      model: settings.model || undefined
    } : { provider: settings.provider };

    const summary = await api(`/api/meetings/${current.id}/summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    renderSummary(summary);
    status(`已完成 AI 會議整理（${summary.provider || providerLabel}）。`);
  } catch (error) {
    status(error.message, true);
  } finally {
    setBusy(false);
  }
};

readDraft(true);
loadList();
