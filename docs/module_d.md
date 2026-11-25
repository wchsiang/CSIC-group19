# D：跨會議待辦總覽

把所有會議的行動項目集中在一個清單，可依負責人篩選、勾選完成。設計理由見 [DECISIONS.md](../DECISIONS.md) 2026-11-25 條目。

## 資料

`action_items` 資料表：`id`、`meeting_id`、`assignee`、`task`、`due`（原文文字，可為 null）、`status`（`open`／`done`）、`origin`（`ai`／`manual`）、`missing_from_source`、`position`、`done_at`、`created_at`、`updated_at`。

舊資料庫啟動時會自動從 `summaries.action_items` 補建待辦，不需手動遷移。

## 重新產生與編輯時的對應規則

每次儲存摘要（`POST`／`PUT /api/meetings/{id}/summary`）都會把新清單對應到既有待辦：

1. 有 `id` 的項目（網頁編輯表單會帶上）直接對應。
2. 同負責人、事項文字去除空白與標點後相同。
3. 同負責人、事項相似度 ≥ 0.6，取最相似者。

| 情況 | AI 重新產生 | 人工編輯 |
|---|---|---|
| 配對成功 | 保留 id 與完成狀態；更新內容，但人工改過的項目保留人工內容 | 保留 id 與完成狀態；內容有改則標為 manual |
| 新清單多出的項目 | 新增 | 新增（manual） |
| 舊項目未出現在新清單 | 標記 `missing_from_source`，等使用者保留或移除 | 刪除 |

## API

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/action-items` | 回傳 `{"items": [...]}`，未完成在前。可加 `?assignee=小明`、`?status=open|done`。每項另含 `meeting_title`、`summary_stale` |
| PUT | `/api/action-items/{id}` | `{"status":"done"}`／`{"status":"open"}` 切換完成；`{"keep":true}` 清除「原文已無此項」標記 |
| DELETE | `/api/action-items/{id}` | 移除待辦 |

`GET /api/meetings/{id}/summary` 的 `action_items` 改為回傳資料表中的項目（多了 `id`、`status` 等欄位），原有欄位不變。錯誤格式與其他 API 相同：400、403（跨來源）、404、413、415。

## 測試

```powershell
python -m unittest tests.test_module_d -v
node --test tests/test_frontend.cjs
```

## 人工驗收

1. 建立會議：`小明：我負責前端畫面，週五前完成。`／`小華：我負責後端 API。`，產生摘要，確認待辦總覽出現兩項。
2. 勾選「前端畫面」，確認從清單消失；勾「顯示已完成」後以刪除線顯示。
3. 把原文改成「前端畫面設計」並刪除小華那行，儲存後重新產生：前端畫面設計仍為已完成；後端 API 顯示「原文已無此項」，按保留或移除確認行為。
4. 以「✏️ 編輯」修改某項期限後重新產生，確認人工期限沒有被覆蓋。
5. 窄螢幕與鍵盤操作檢查勾選框、篩選與按鈕。

2026-11-25 已用 Chromium（Playwright）自動操作第 1–3 步並確認結果與窄螢幕無水平捲動；真實使用者與手動操作驗收尚未進行。
