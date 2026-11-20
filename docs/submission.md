# 提交 A 模組

目前為 ZIP 解壓的工作副本，沒有原 Repository 的 `.git` 歷史；尚未開分支、提交或建立遠端 PR。不可把重新初始化的 Git 歷史覆蓋到原專案。

## PR 內文（依既有模板）

### What this PR does

新增會議原文收集功能：學生可建立會議、貼上或匯入 UTF-8 .txt、保存後重新開啟修改，供後續 AI 整理功能串接。可選擇保留未儲存的瀏覽器草稿，重新開啟後復原或清除。

### Decision

Decision: 以 Python 標準函式庫與 SQLite 建立 A 初版，保留原文並以 revision 防止過期更新覆蓋。

Why: 目前 Repository 尚無應用程式；先提供能本機執行、可供 B／C／D 串接的功能。

Alternative deferred: 即時錄音與語音辨識；團隊是否接受本技術提案仍待 review。

Led by: Howard Lin（A 模組），尚非四人團隊共識。

### Validation

- `python -m unittest discover -s tests -v`：5 項通過。
- `node --test tests/test_frontend.cjs`：6 項通過。
- `node --check static/app.js`：通過。
- 第一版由 Howard 回報操作正常；新匯入／草稿功能真實瀏覽器驗收待補。
- 詳見 `docs/verification.md`。

### AI use

使用 OpenAI Codex 協助程式、測試與文件。提示詞及採用／修改內容見 `docs/prompt_log.md`；具體模型版本未確認。需由非作者組員理解並審查後才能合併。

### Review focus

請確認技術方案與原文 API 是否符合後續整理、共同確認及回顧功能；檢查 revision 衝突處理。此 PR 尚未提供 AI 摘要或雙人共同確認。

## 建立遠端 PR

可使用 GitHub Desktop：登入自己的帳號，clone 原 Repository，建立 `feat/meeting-input` 分支，將此工作副本的變更檔案複製進 clone（保留 clone 的 `.git`），確認差異不包含 `data/` 與真實逐字稿，commit 後 publish branch，再 Create Pull Request。

或使用 GitHub 網頁：先從當前 main 建立 `feat/meeting-input` 分支，再在該分支 Upload files；從這份工作副本上傳新增程式、測試、docs、README、DECISIONS、.gitignore 與 workflow，維持目錄結構。不要上傳整份 ZIP 作為程式碼，也不要提交 __pycache__ 或 data。

若 main 自下載後已有變更，先取得最新版並檢查差異，不要直接用舊副本覆蓋原有文件。

### 個人門檻

此完整實作提交成一個 PR 就只算一個；不宣稱已滿足兩個 merged PR。第二個 PR 應承載後續實際整合或有意義的改進／修正，經另一輪審查後合併。若團隊希望分期 review，可在提交前實際拆出「核心保存」與「匯入／草稿」的可運作變更，不能重複提交相同內容湊數。

## 其他待確認

- CONTRIBUTORS.md 目前只有三位姓名；第四位與 GitHub 帳號需由團隊確認。
- 初始 Steward 是既有紀錄中的温竣翔；目前當值者與交接需確認，不能自行推定。
- API 與技術方案需團隊接受；完整 CP2 雙人原型及團隊活動尚未完成。
