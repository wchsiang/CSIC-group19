"""Module B: Meeting transcript analysis and structured summarization.
Supports Google Gemini, Anthropic Claude, OpenAI, and offline heuristic rule engine.
Python standard library only.
"""
import json
import os
import re
import urllib.error
import urllib.request

PROMPT_TEMPLATE = """你是一個精準的會議紀錄與整理專家。請根據以下會議逐字稿內容，萃取結構化會議整理。
【嚴格規則】
1. 會議摘要 (summary)：客觀精簡總結會議核心重點、討論方向與主要結論。請用流暢的繁體中文段落，勿直接照抄零碎句子。
2. 決策事項 (decisions)：列出會議中全體或相關人員明確達成共識、同意或決定的事項清單（字串陣列）。若討論中「尚未決定」、「待確認」或「下次再議」的事項絕對不可列入。
3. 行動項目 (action_items)：列出每個人的分工任務。包含 assignee (負責人), task (待辦內容), due (完成期限)。
   【重要限制】：AI 不應替沒有明確期限的工作自行設定日期；若逐字稿未明確提及期限，due 請填 null（不可自創或猜測時間）。

會議標題：{title}
會議逐字稿：
{transcript}

請回傳合法 JSON 格式，包含 summary, decisions, action_items 三個欄位。
範例格式：
{{
  "summary": "本次會議針對...",
  "decisions": ["決策1", "決策2"],
  "action_items": [
    {{"assignee": "小明", "task": "建立會議與文字輸入", "due": "週五前"}},
    {{"assignee": "小華", "task": "AI 整理", "due": null}}
  ]
}}
"""


def _parse_json_from_llm(raw: str) -> dict:
    """Safely extracts JSON dict from LLM response text."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    data = json.loads(clean.strip())
    if not isinstance(data, dict):
        raise ValueError("模型回應之格式非 JSON 物件。")

    return {
        "summary": str(data.get("summary", "")).strip(),
        "decisions": [str(d).strip() for d in data.get("decisions", []) if str(d).strip()],
        "action_items": [
            {
                "assignee": str(item.get("assignee", "未指定")).strip() if item.get("assignee") else "未指定",
                "task": str(item.get("task", "")).strip(),
                "due": str(item.get("due")).strip() if item.get("due") and str(item.get("due")).lower() not in ["none", "null", ""] else None
            }
            for item in data.get("action_items", [])
            if isinstance(item, dict) and item.get("task")
        ]
    }


def _call_gemini(transcript: str, title: str, api_key: str, model: str = None) -> dict:
    model_name = model or "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    prompt = PROMPT_TEMPLATE.format(title=title, transcript=transcript)
    req_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_json_from_llm(raw_text)
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise ValueError(f"Gemini API 錯誤 ({err.code}): {msg}")
    except Exception as err:
        raise ValueError(f"Gemini 連線異常: {str(err)}")


def _call_claude(transcript: str, title: str, api_key: str, model: str = None) -> dict:
    model_name = model or "claude-3-5-haiku-20241022"
    url = "https://api.anthropic.com/v1/messages"
    prompt = PROMPT_TEMPLATE.format(title=title, transcript=transcript)
    req_body = {
        "model": model_name,
        "max_tokens": 4096,
        "temperature": 0.2,
        "system": "You are a professional meeting minutes secretary. Output JSON only, no markdown backticks, no commentary.",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(req_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_text = data["content"][0]["text"]
            return _parse_json_from_llm(raw_text)
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise ValueError(f"Claude API 錯誤 ({err.code}): {msg}")
    except Exception as err:
        raise ValueError(f"Claude 連線異常: {str(err)}")


def _call_openai(transcript: str, title: str, api_key: str, model: str = None) -> dict:
    model_name = model or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    url = f"{base_url.rstrip('/')}/chat/completions"
    prompt = PROMPT_TEMPLATE.format(title=title, transcript=transcript)
    req_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a professional meeting minutes assistant. Always output valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(req_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_text = data["choices"][0]["message"]["content"]
            return _parse_json_from_llm(raw_text)
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise ValueError(f"OpenAI API 錯誤 ({err.code}): {msg}")
    except Exception as err:
        raise ValueError(f"OpenAI 連線異常: {str(err)}")


def test_llm_connection(provider: str, api_key: str, model: str = None) -> dict:
    """Verifies that the provided API key and provider work correctly."""
    if not api_key or not api_key.strip():
        raise ValueError("請輸入 API Key。")
    p = (provider or "").lower().strip()
    test_transcript = "小明：明天早上九點開會確認分工。"
    test_title = "連線測試"
    if p == "gemini":
        _call_gemini(test_transcript, test_title, api_key.strip(), model)
    elif p == "claude":
        _call_claude(test_transcript, test_title, api_key.strip(), model)
    elif p == "openai":
        _call_openai(test_transcript, test_title, api_key.strip(), model)
    else:
        raise ValueError(f"不支援的模型提供商：{provider}")
    return {"ok": True, "message": f"{provider.capitalize()} API 連線驗證成功！"}


def analyze_transcript(transcript: str, title: str = "", provider: str = None, api_key: str = None, model: str = None) -> dict:
    """Analyzes transcript using specified provider or falls back to heuristics."""
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("會議內容不能為空。")

    # 1. Direct explicit API key passed from request
    if api_key and api_key.strip():
        chosen = (provider or "").lower().strip()
        if not chosen:
            if api_key.startswith("AIza"):
                chosen = "gemini"
            elif api_key.startswith("sk-ant-"):
                chosen = "claude"
            elif api_key.startswith("sk-"):
                chosen = "openai"
            else:
                chosen = "gemini"

        if chosen == "gemini":
            res = _call_gemini(transcript, title, api_key.strip(), model)
            res["provider"] = "Google Gemini"
            res["model"] = model or "gemini-3.5-flash"
            return res
        elif chosen == "claude":
            res = _call_claude(transcript, title, api_key.strip(), model)
            res["provider"] = "Anthropic Claude"
            res["model"] = model or "claude-3-5-haiku-20241022"
            return res
        elif chosen == "openai":
            res = _call_openai(transcript, title, api_key.strip(), model)
            res["provider"] = "OpenAI"
            res["model"] = model or "gpt-4o-mini"
            return res
        elif chosen == "heuristic":
            res = extract_heuristics(transcript, title)
            res["provider"] = "本機離線規則"
            res["model"] = "Heuristic Engine"
            return res
        else:
            raise ValueError(f"不支援的模型提供商：{chosen}")

    # 2. Check environment variables
    env_gemini = os.environ.get("GEMINI_API_KEY")
    if env_gemini and (not provider or provider == "gemini"):
        try:
            res = _call_gemini(transcript, title, env_gemini.strip(), model)
            res["provider"] = "Google Gemini (環境變數)"
            res["model"] = model or "gemini-3.5-flash"
            return res
        except Exception:
            pass

    env_claude = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if env_claude and (not provider or provider == "claude"):
        try:
            res = _call_claude(transcript, title, env_claude.strip(), model)
            res["provider"] = "Anthropic Claude (環境變數)"
            res["model"] = model or "claude-3-5-haiku-20241022"
            return res
        except Exception:
            pass

    env_openai = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if env_openai and (not provider or provider == "openai"):
        try:
            res = _call_openai(transcript, title, env_openai.strip(), model)
            res["provider"] = "OpenAI (環境變數)"
            res["model"] = model or "gpt-4o-mini"
            return res
        except Exception:
            pass

    # 3. Default fallback to heuristic rule engine
    res = extract_heuristics(transcript, title)
    res["provider"] = "本機離線規則"
    res["model"] = "Heuristic Engine"
    return res


def extract_heuristics(transcript: str, title: str = "") -> dict:
    """Deterministic heuristic extraction from meeting transcripts."""
    lines = [line.strip() for line in transcript.strip().splitlines() if line.strip()]
    topic = title.strip()
    speakers = []
    dialogues = []
    decisions = []
    action_items = []

    negative_decision_keywords = ["還沒有決定", "尚未決定", "未定", "尚未確認", "還沒確認", "下次確認", "待確認"]

    for line in lines:
        if (line.startswith("【") and line.endswith("】")) or (line.startswith("[") and line.endswith("]")):
            continue
        topic_match = re.match(r"^(?:會議)?(?:主題|題目)[：:]\s*(.+)$", line)
        if topic_match:
            topic = topic_match.group(1).strip()
            continue
        speaker_match = re.match(r"^([^：:\s]{1,15})[：:]\s*(.+)$", line)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            content = speaker_match.group(2).strip()
            if speaker not in speakers and speaker not in ["主席", "記錄", "所有人"]:
                speakers.append(speaker)
            dialogues.append((speaker, content))
        else:
            dialogues.append((None, line))

    for speaker, content in dialogues:
        action_match = re.search(r"(?:我|(?:由\s*)?([^，。；：\s]{2,10}))?\s*負責(?:處理|執行|進行)?\s*([^\n]+)", content)
        if action_match:
            raw_assignee = action_match.group(1)
            raw_task_clause = action_match.group(2).strip()
            assignee = raw_assignee.strip() if raw_assignee else (speaker or "待指派")

            due_match = re.search(r"([^\s，。；]+(?:前|之前|截止|前完成|交付))", raw_task_clause)
            due = None
            task = raw_task_clause
            if due_match:
                due = due_match.group(1).removesuffix("完成").strip()
                task = re.sub(r"[，、\s]*" + re.escape(due_match.group(1)) + r"(?:完成)?[，。\s]*", "", task).strip()
            else:
                task = re.sub(r"[，。；\s]+$", "", task).strip()

            if task:
                action_items.append({
                    "assignee": assignee,
                    "task": task,
                    "due": due
                })

        clauses = [c.strip() for c in re.split(r'[，。；;\n]+', content) if c.strip()]
        decision_keywords = ["先使用", "採用", "決定", "決議", "同意", "達成共識", "確立", "確認使用", "不應"]

        for clause in clauses:
            is_negative = any(neg in clause for neg in negative_decision_keywords)
            has_decision = any(dk in clause for dk in decision_keywords)
            if has_decision and not is_negative:
                clean_decision = re.sub(r"^(?:同意[。，、]?\s*|好的[。，、]?\s*|我們|大家)+", "", clause).strip()
                if clean_decision and not any(clean_decision == d for d in decisions):
                    if "負責" not in clean_decision and len(clean_decision) >= 4:
                        decisions.append(clean_decision)

    summary_parts = []
    if topic:
        summary_parts.append(f"本次會議主題為「{topic}」。")
    if speakers:
        summary_parts.append(f"出席成員包含：{'、'.join(speakers)}。")
    if action_items:
        tasks_summary = "、".join([f"{item['assignee']}負責{item['task']}" for item in action_items[:3]])
        summary_parts.append(f"會中針對各項工作進行分工規劃，包括 {tasks_summary} 等。")
    if decisions:
        summary_parts.append(f"討論中達成之重要共識包含：{'；'.join(decisions)}。")

    summary_text = "".join(summary_parts) if summary_parts else "會議討論完成，已提取相關紀錄事項。"
    return {
        "summary": summary_text,
        "decisions": decisions,
        "action_items": action_items
    }
