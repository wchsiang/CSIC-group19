# AI interaction log — A & B modules

## 區域網路連線開關 `--lan`（2026-11-23 至 2026-11-25）

使用者提示原文：
1. 「add a switch to connect from local network instead of localhost (not default because currently no auth).」
2. 「1. create a new branch for this feature and syncing (which will be implemented later) first, and write down what should be documented (refer to AI Usage Guidelines) 2. if possible, test whether `--lan` works as expected in CI」
3. 「Iʼll manually push after syncing feature completes; related documents can be adjusted」
4. 「Split local network support and syncing into two PRs」
5. 「The sync commit will be rebased and partly rewritten after module D merged. Edit docs from the new branch that only contains local network support, then write PR description draft.」
6. 「go ahead with the docs commit」

採用：
1. 原先建立 `feat/lan-sync` 分支，同時承載本功能與之後的同步功能；依第 4、5 點提示拆成兩個 PR，本功能改由只含 `--lan` 的 `feat/lan` 分支提出。
2. `app.py`：新增 `--lan`（預設關閉）、`parse_args()` 與 `lan_ip()`；啟用時綁定 `0.0.0.0`，顯示區域網路網址與無驗證警告。啟動訊息改用實際連接埠，以支援 `--port 0`。
3. `tests/test_lan.py`：檢查參數預設值；以子行程啟動真正的 `app.py`，驗證預設模式無法從區域網路 IP 連線、`--lan` 模式可連線，且帶區域網路 Origin 的 `POST /api/meetings` 回傳 201。若主機沒有非 loopback 的 IPv4 位址則略過。CI 既有的 `unittest discover` 步驟會自動執行，不需修改 workflow。
4. 文件：README、`docs/meeting_input.md` 使用說明，`DECISIONS.md` 決策紀錄。

修改：初版計畫沒有建立分支、AI 使用紀錄及 CI 測試；依第 2 點提示補上。依第 3 點提示，不由 AI 推送分支或建立 PR。依第 5 點提示，`DECISIONS.md` 與本紀錄改寫為只描述 `--lan`，並順帶移除 `docs/meeting_input.md` 中已過時的「未實作 AI 摘要」。
未採用：預設開放 `0.0.0.0`、任意 `--host` 參數（理由見 `DECISIONS.md`）。
驗證（2026-11-25，`feat/lan`）：`python -m unittest discover -s tests -v` 19 項通過，`test_lan` 的四項測試皆實際執行、未被略過；`node --check static/app.js` 與 `node --test tests/test_frontend.cjs` 13 項通過（本次未修改前端）。GitHub Actions 結果待推送後確認。
尚待：依更新後的 AI_USAGE_GUIDELINES.md，作者在 PR 勾選已逐行閱讀並能自行說明，審查者確認 PR 中的修改說明與風險和實際差異相符；多裝置同步另開 PR。

AI 工具：Claude Code（Claude Opus 5.5）。

---

## B 模組：介面 API Key 設定與多模型支援（Gemini / Claude / OpenAI）（2026-11-22）

使用者提示原文：
1. 「現在的ai整理部分看起來不像是由LLM整理，比較像是先hardcode完提取填入，是否應該直接請模型整理」
2. 「現在是只要使用者在環境變數中設定LLM_API_KEY就會請LLM整理，如果沒有設定就會使用extract_heuristics對嗎」
3. 「請幫我照你的建議改進，並且增加Claude的選擇」

採用：
1. `summarizer.py`：以 Python 標準庫實作 **Google Gemini API**、**Anthropic Claude API** 與 **OpenAI API** 的原生呼叫與結構化 JSON 解析，取消原有的靜默錯誤吞沒（Silent Fallback），提供明確錯誤訊息；新增 `test_llm_connection()` 供連線測試。
2. `app.py`：新增 `/api/test-llm` 端點測試連線；`POST /api/meetings/{id}/summary` 支援接收前端傳入之 provider、api_key 與自訂 model；資料表記錄來源 `provider`。
3. `static/`：
   - 頁首新增「⚙️ AI 模型設定」按鈕與 `<dialog>` 彈出式視窗。
   - 支援切換 Google Gemini、Anthropic Claude、OpenAI 與本機離線規則模式。
   - 提供官方取 Key 連結、密碼眼睛切換、連線測試按鈕、清除金鑰功能。
   - 金鑰以 `localStorage` 暫存於用戶瀏覽器，不儲存於伺服器資料庫。
   - 摘要完成後顯示整理模型來源標籤（如 `✨ 由 Google Gemini 整理`）。
4. `tests/test_module_b.py`：新增針對多模型解析的 Mock 單元測試與 `/api/test-llm` 測試，12 項測試全數通過。

AI 工具：Antigravity AI (Gemini)。

---

## B 模組：AI 會議整理與待辦萃取初版（2026-11-22）

使用者提示原文：「請幫我實作module B的部分，並新增test_module來驗證程式碼的可行性」

採用：
1. `summarizer.py`：實作逐字稿分析引擎，從會議內容萃取結構化 `summary`（摘要）、`decisions`（決策共識）、`action_items`（分工與期限）。嚴格遵守「AI 不應替沒有明確期限的工作自行設定日期」限制；未提供 API 金鑰時使用內建自然語言規則引擎，可單元測試與離線使用；具備 LLM 呼叫接口。
2. `app.py`：新增 `summaries` 資料表，以外鍵關聯 `meetings` 表；實作 `POST /api/meetings/{id}/summary`（產生摘要）、`GET /api/meetings/{id}/summary`（讀取摘要，自動比對 `source_revision` 與 `revision` 判斷是否過期 `is_stale`）、`PUT /api/meetings/{id}/summary`（支援手動編輯調整）。
3. `tests/test_module_b.py`：新增獨立測試模組，包含虛構逐字稿萃取規則驗證（含無明確期限不虛構日期、否定決策排除）、API 完整生命週期與資料庫持久化、原文修改後 `is_stale` 過期偵測與重產更新、手動編輯更新及錯誤邊界處理。
4. `static/`：前端增加「AI 整理與會議結論」區塊，含即時狀態 Badge、過期警示 Banner、重要決策清單、分工行動項目表格，以及「產生／重新產生摘要」互動按鈕。

AI 工具：Antigravity AI (Gemini)。

---

## 後續：版本衝突復原（2026-11-20）

使用者提示原文：「cp2好像是一個人要有2個pr，我們現在能來完成第二個嗎?」

採用：針對第一版收到 409 後只能手動複製文字的缺口，增加另存新會議、確認後重新載入最新版、UTF-8 原文備份下載與五個回歸案例。AI 工具為 OpenAI Codex，具體模型版本未確認。沿用原 API，沒有強制覆寫新版的路徑。16 項自動測試及語法檢查通過；真實瀏覽器驗收與他人審查尚待進行。

依 AI_USAGE_GUIDELINES.md 記錄直接產生實作與文件的互動。工具：OpenAI Codex；此紀錄無法從可見資訊可靠確認具體模型版本，因此不臆填型號。日期：2026-11-20。使用者：Howard Lin。

## 1. 初版實作

使用者提示原文：「那我就負責a的部分吧。請你現在開始幫助我完成我負責的部分」

上下文：A 為建立會議、輸入標題與原始討論文字、保存／載入及錯誤處理；B／C／D 分別負責整理、共同確認與回顧。

採用：Python HTTP API、SQLite 原文保存、HTML/CSS/JavaScript 輸入介面、伺服器驗證、revision 衝突檢查與測試。

修改：首次測試發現 SQLite 連線未關閉，造成 Windows 暫存檔清理失敗；改為明確關閉連線後重跑通過。

未納入：AI 摘要、錄音、登入、雙人確認及待辦管理，不宣稱其他組員的範圍已完成。

## 2. 輸入改善與交接

使用者提示原文：「那就請你繼續完成我要做的部分，如果有一定要我操作的部分再叫我」

採用：UTF-8 .txt 匯入、覆蓋確認、大小／內容驗證；可選擇保留瀏覽器草稿、恢復與清除；6 項模擬 DOM 測試；API 與 PR 交接文件。

限制：草稿不是雲端同步；新增功能尚無真實瀏覽器驗收證據。

## 3. 整合下載的 Repository

使用者提示原文：「放好了」

上下文：使用者依前次指示提供 GitHub ZIP；檢查發現只有規劃文件、既有 PR template 及初始 Steward 紀錄，沒有應用程式或 AGENTS.md。

採用：將 A 實作整合至根目錄，補 README、API 文件、根目錄決策紀錄、測試 workflow 與提交說明。保留原評估計畫、AI 規範及貢獻者檔案，沒有替團隊填入 approvals 或測試發現。

## 4. 回應 PR #7 與 #8 審查

日期 2026-11-22。工具為 OpenAI Codex，具體模型版本未確認。

提示摘要：依 Code Steward 的回饋另開 PR，新增會議刪除、隔離多分頁草稿、補登版本衝突決策並區分另存標題。

採用：依會議儲存瀏覽器草稿，支援舊草稿恢復。刪除時確認並比對 revision。另存標題加上「(衝突備份)」，補上決策與回歸測試。多人寫入驗證涵蓋同一服務上的並行請求。

## 人工確認狀態

- 使用者回報第一版本機操作沒有問題；未聲稱完成逐行程式碼審查。
- 其他組員能否解釋程式、Code Steward 審查及團隊技術決策：待完成。
- 每個實際 PR 應揭露 AI 協助並連結本紀錄，由非作者組員完成 review 後再合併。
