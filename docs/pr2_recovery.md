# PR 2：會議原文衝突復原

## PR 標題

feat: recover meeting edits after a version conflict

## What this PR does

兩個分頁編輯同一份會議時，舊分頁儲存會收到 409。新增復原操作：保留輸入並另存新會議，或確認捨棄後載入最新版；也能先將目前原文下載為 UTF-8 .txt 備份。

## Decision

Decision: 沿用 revision 檢查與現有 POST／GET API，明確提供另存與載入操作。

Why: 舊版雖避免覆蓋，使用者仍需自行複製輸入才能復原。另存可保住原文，同時維持新版紀錄。

Alternative rejected: 自動提高 revision 重送，會覆蓋別人的更新。

Led by: Howard Lin 的 A 模組實作提案，待 Code Steward review。

## Validation

- 11 項前端事件邏輯測試通過，新增 5 項：409 保留輸入、另存不帶舊 revision、取消／失敗載入不改原文、成功載入清除已復原草稿、UTF-8 備份。
- 5 項 API 測試及 JavaScript 語法檢查通過。
- 模擬 DOM 無法驗證真實瀏覽器下載與對話框，以下人工驗收待完成。

## AI use

OpenAI Codex 協助實作、測試與文件，見 `docs/prompt_log.md`。需非作者組員理解並審查後再合併。

## 人工驗收

1. 執行 `python app.py --port 8001`，在兩個分頁開啟 http://127.0.0.1:8001 並載入同一份已儲存會議。
2. 第一頁修改並儲存；第二頁輸入不同內容後儲存，應顯示衝突操作且保留輸入。
3. 第二頁按下載備份，確認檔案中文、多行內容正確，頁面仍是未儲存狀態。
4. 按另存新會議，確認列表出現新紀錄，原會議仍是第一頁的版本。
5. 再製造一次衝突，取消載入應保留輸入；確認載入則顯示最新版本，之後可正常更新。

## 建立第二個 PR

此資料夾是獨立 Git 工作副本，分支為 `feat/transcript-recovery`，起點是 PR #7 的 `7f4056e`，不是重新建立歷史。

GitHub Desktop：File → Add local repository，選擇 `C:\Users\HowardLin\Desktop\csic_cp2\meeting-recovery`，確認 Current Branch 為 feat/transcript-recovery。檢查差異後 commit，Publish branch，再 Create Pull Request。

若 PR #7 尚未合併，第二個 PR 應先以 `feat/meeting-input` 為 base，這樣只顯示本次改善，並在內文寫「Depends on #7；請勿先合併」。#7 合併後將 base 改為 main，確認 Files changed 只包含本次改善，必要時同步 main。若 #7 以 squash 合併，差異可能需重新整理，屆時再處理。

兩個 PR 都需各自有實際 review 與合併；不可把第二個直接合併回第一個功能分支就認為已完成 main 的整合。
