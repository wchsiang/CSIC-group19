# CSIC Group 19 — Meeting Notes

協助討論分組作業的學生減少手動記錄負擔，並改善會後對討論內容的理解與記憶。原始問題與評估構想見 [EVALUATION_PLAN.md](EVALUATION_PLAN.md)。

## 目前進度

A 模組已實作會議建立、文字輸入、保存、載入與修改，以及 UTF-8 文字檔匯入和可選的瀏覽器草稿復原。AI 整理、雙人加入／共同確認及待辦管理尚未實作，因此目前還不是完整的 CP2 雙人原型，也尚未驗證能減少真實開會時的分心。

這次以文字逐字稿作為輸入。Python／SQLite 是 A 的初版技術提案，仍待團隊 review 確認。

## 本機執行

需要 Python 3.10 以上，不需要安裝額外套件。請在包含 `app.py` 的目錄開啟 PowerShell：

```powershell
python app.py
```

瀏覽 http://127.0.0.1:8000 。按 Ctrl+C 停止。若連接埠被占用，使用 `python app.py --port 8001`。

1. 填入會議標題，貼上討論內容，或選擇 UTF-8 `.txt` 逐字稿。
2. 按「儲存會議」，再從左側列表重新開啟。
3. 修改並按「儲存變更」。重啟服務後仍可讀取紀錄。
4. 如需草稿復原，自行勾選「在此瀏覽器保留未儲存草稿」；重新開啟後可恢復或清除。
5. 若儲存遇到版本衝突，可另存新會議，或確認捨棄輸入後載入最新版。可先按「下載目前文字備份」保存原文；下載不會更新資料庫，標題使用檔名保存。

可使用 [虛構範例逐字稿](docs/sample_transcript.txt) 試用。會議資料存於 `data/meetings.sqlite3`，不應提交到 GitHub。草稿存在同一瀏覽器、同一來源的 localStorage，與資料庫儲存分開。

## 檢查

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/test_frontend.cjs
```

Node.js 僅供前端檢查使用；操作產品只需要 Python。前端測試使用模擬 DOM，實際瀏覽器驗收項目見 [驗收紀錄](docs/verification.md)。

## 開發與交接

- [API、模組限制與人工驗收步驟](docs/meeting_input.md)
- [D 模組：跨會議待辦總覽](docs/module_d.md)
- [A 模組實作選擇與待團隊確認事項](DECISIONS.md)
- [AI 提示詞紀錄](docs/prompt_log.md)
- [PR 說明草稿與提交方式](docs/submission.md)
- [AI 使用規範](AI_USAGE_GUIDELINES.md)

需由非作者組員理解實作並依 AI 使用規範完成審查後才能合併；本機檔案不代表已有 merged PR。
