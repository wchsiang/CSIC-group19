# Decisions Log

## 2026-09-21 — Initial code steward（既有紀錄）

What: 温竣翔 is the initial code steward for the team.
Why: volunteered.

來源：原 Repository 的 `.github/DECISIONS.md`。此處保留既有內容；沒有新增或推定任何 Steward 交接。

## 2026-11-20 — A 模組實作選擇（待團隊審查）

狀態：Howard Lin 負責的 A 模組與 AI 協助實作；以下為工作副本中的實作選擇，不代表四人已共同決議。PR 連結待建立後補上。

- 問題：學生目前需手動記錄；A 需提供可靠的會議原文輸入，讓後續整理與回顧功能可以串接。
- 選擇：先支援貼上文字與 UTF-8 .txt 匯入，使用 Python 標準函式庫提供同來源 API，以 SQLite 保存原文。
- 理由：目前 Repository 無應用程式或框架；本機可直接運作，無須外部帳號或套件下載。
- 暫緩方案：即時錄音／語音辨識涉及新的服務與錯誤情境；先驗證原文收集與下游串接。尚未驗證文字輸入是否降低真實會議的分心。
- 資料選擇：原文與後續 AI 產出分開。使用 UUID、UTC 時間與 revision；舊版更新回傳 409，防止覆蓋新原文。
- 草稿選擇：瀏覽器草稿採自行勾選保留，可恢復或清除；預設不保存。
- 待確認：是否接受此技術、API 欄位、B 的來源 revision、C 的成員與確認資料、D 的待辦資料。若團隊已有未公開實作，應對齊其介面。
- 證據：`app.py`、`static/`、`tests/`、`docs/verification.md`、`docs/prompt_log.md`。

## 2026-11-20 — 會議原文衝突復原選擇（PR 2）

狀態：已由 Howard Lin 提案並實作，待 Code Steward review。

- 問題：版本衝突（409）發生時，舊版僅能提示錯誤，使用者需自行複製文字至剪貼簿，容易造成資料遺失。
- 選擇：沿用 revision 機制，新增「另存新會議」（POST 全新會議紀錄）與「確認捨棄後載入最新版」（GET 刷新），並提供純前端 UTF-8 .txt 本機備份下載。
- 理由：維持資料一致性，拒絕自動累加 revision 強制覆蓋他人更新；另存可保住輸入文字，同時維護最新版本紀錄。
- 證據：`static/app.js`、`static/index.html`、`tests/test_frontend.cjs`。

## 2026-11-22 — B 模組：AI 會議整理與待辦萃取架構

狀態：Module B 實作完成，待團隊審查。

- 問題：學生開會時需手動筆記容易分心；B 模組需自動從會議逐字稿中萃取會議摘要、重要共識決策與行動項目（分工與期限）。
- 選擇：
  1. **資料架構**：採獨立 `summaries` 資料表（`meeting_id`, `source_revision`, `summary`, `decisions`, `action_items`, `provider`），以外鍵關聯 `meetings` 表；**絕對不覆寫原文**。
  2. **版本過期偵測（Staleness Detection）**：記錄 `source_revision`。當原文 `revision` 大於 `source_revision` 時，系統自動標記 `is_stale: true` 並在介面提示使用者重新產生。
  3. **分析引擎**：採用「本機確定性語法與規則萃取 + 可選環境變數 LLM 擴充」，確保在無網路、無外部 API 金鑰的環境下 100% 可單元測試與離線運行。
  4. **嚴格禁止捏造期限**：恪守「AI 不應替沒有明確期限的工作自行設定日期」原則，僅於原文明確提及時間時標記 `due`，未提及則填 `None`。
- 證據：`summarizer.py`、`app.py`、`tests/test_module_b.py`、`static/`。

## 2026-11-22 — B 模組多模型支援與介面金鑰設定（Gemini / Claude / OpenAI）

狀態：已完成實作並通過單元測試。

- 問題：單純依賴本機關鍵字抽取規則過於僵硬，無法理解口語化語境；且使用者需至系統終端機手動配置環境變數，操作門檻高，且原先發生 API 錯誤時容易被靜默吞沒。
- 選擇：
  1. **多模型支援**：全面支援 **Google Gemini**（`gemini-3.5-flash`）、**Anthropic Claude**（`claude-3-5-haiku-20241022`）與 **OpenAI**（`gpt-4o-mini`），均以 Python 原生標準庫 `urllib.request` 實作，維持零第三方套件依賴。
  2. **網頁介面金鑰設定**：提供「⚙️ AI 模型設定」彈出視窗，金鑰安全暫存於使用者瀏覽器（`localStorage`），每次呼叫以同源請求轉發，絕不寫入後端資料庫。
  3. **透明錯誤反饋**：去除靜默忽略錯誤的寫法；若填入之金鑰失效或連線異常，直接返回具體錯誤訊息，並提供連線測試按鈕（`POST /api/test-llm`）。
  4. **相容性與離線保障**：若未填入金鑰，系統平滑支援「本機離線規則抽取」，CI 測試中亦透過 Mock 模擬模型回傳，確保離線與自動化測試 100% 穩定。
- 證據：`summarizer.py`、`app.py`、`static/index.html`、`static/app.js`、`static/style.css`、`tests/test_module_b.py`。
