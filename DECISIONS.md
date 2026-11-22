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

合併前需補上審查者、審查結果、PR 連結；不得填入未發生的團隊活動或 approvals。
