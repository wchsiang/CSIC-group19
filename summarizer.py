"""Module B: Meeting transcript analysis and structured summarization.
Python standard library only, with optional LLM integration.
"""
import json
import os
import re
import urllib.error
import urllib.request


def analyze_transcript(transcript: str, title: str = "") -> dict:
    """Analyze meeting transcript and extract structured summary, decisions, and action items."""
    if not isinstance(transcript, str) or not transcript.strip():
        raise ValueError("會議內容不能為空。")

    # If external LLM key is configured, attempt call with graceful fallback
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if api_key:
        try:
            return _call_llm(transcript, title, api_key)
        except Exception:
            pass

    return extract_heuristics(transcript, title)


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
        # Action item extraction: "我負責...", "由X負責...", "X負責..."
        action_match = re.search(r"(?:我|(?:由\s*)?([^，。；：\s]{2,10}))?\s*負責(?:處理|執行|進行)?\s*([^\n]+)", content)
        if action_match:
            raw_assignee = action_match.group(1)
            raw_task_clause = action_match.group(2).strip()
            assignee = raw_assignee.strip() if raw_assignee else (speaker or "待指派")

            # Check for explicit deadline (never hallucinate a date)
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

        # Decision extraction: clauses with positive agreement/decision keywords
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

    # Formulate readable summary
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


def _call_llm(transcript: str, title: str, api_key: str) -> dict:
    url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
    prompt = f"""你是一個精準的會議紀錄與整理專家。請根據以下會議逐字稿內容，萃取結構化會議整理。
嚴格規則：
1. 會議摘要 (summary)：客觀精簡總結會議核心重點。
2. 決策事項 (decisions)：列出會議中明確達成共識或決定的事項。尚未決定或待確認的事項不可列入。
3. 行動項目 (action_items)：列出每個人的分工任務。包含 assignee (負責人), task (待辦內容), due (完成期限)。
   重要限制：AI 不應替沒有明確期限的工作自行設定日期；若逐字稿未明確提及期限，due 請填 null。

會議標題：{title}
會議內容：
{transcript}

請回傳合法 JSON 格式，包含 summary, decisions, action_items 三個欄位。
範例格式：
{{
  "summary": "...",
  "decisions": ["..."],
  "action_items": [{{"assignee": "小明", "task": "...", "due": "週五前"}}]
}}
"""
    req_data = json.dumps({
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": "You are a professional meeting minutes assistant. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        content = res["choices"][0]["message"]["content"]
        data = json.loads(content)
        return {
            "summary": str(data.get("summary", "")),
            "decisions": list(data.get("decisions", [])),
            "action_items": list(data.get("action_items", []))
        }
