"""Claude API integration for signal classification and stack extraction.

Two prompts, two models:
  - Haiku (claude-haiku-4-5): bulk classification — every job description, every RSS entry.
  - Sonnet (claude-sonnet-4-6): long/ambiguous content (HN comments or blog posts >2000 chars).

Both prompts are static per call pattern, so we rely on prompt caching for the system
message — the per-request content is the only thing that changes.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

import anthropic

from app.config import settings
from app.utils.text_cleaner import normalize_tech_name, truncate

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


SIGNAL_CLASSIFICATION_SYSTEM = """You classify text about companies for hiring intent and tech stack signals.

Return JSON only, matching this schema exactly:
{
  "has_hiring_signal": true | false,
  "signal_type": "funding" | "news" | "ats_job" | "hn_whos_hiring" | "none",
  "confidence": 0.0-1.0,
  "roles_mentioned": [string, ...],
  "technologies_mentioned": [string, ...],
  "evidence": "<direct quote, <=160 chars>",
  "summary": "<one sentence>"
}

Rules:
- has_hiring_signal=true only with genuine current/imminent hiring evidence (open role, funding event, announced expansion).
- technologies_mentioned must be specific, normalized tech names (lowercase, no versions): "React.js" -> "react", "Node 18" -> "node".
- No markdown, no prose outside the JSON object."""


STACK_EXTRACTION_SYSTEM = """You extract technologies from job postings for a given company.

Return JSON only, matching this schema exactly:
{
  "technologies": { "<tech_name>": 0.0-1.0, ... },
  "categories": {
    "frontend": [string, ...],
    "backend":  [string, ...],
    "mobile":   [string, ...],
    "database": [string, ...],
    "cloud":    [string, ...],
    "devops":   [string, ...]
  }
}

Confidence rules:
- Required / must-have: 0.9
- Preferred / nice-to-have: 0.5
- Inferred from context: 0.3

Normalize tech names (lowercase, no versions). No markdown."""


HN_COMMENT_SYSTEM = """You extract structured hiring info from a Hacker News "Who's Hiring" comment.

Return JSON only, matching this schema exactly:
{
  "company": "<company name or null>",
  "location": "<location string or null>",
  "remote": true | false | null,
  "technologies": [string, ...],
  "roles": [string, ...],
  "summary": "<one sentence or null>"
}

Normalize tech names (lowercase, no versions). No markdown."""


async def _invoke(
    system: str,
    content: str,
    *,
    model: str,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    client = _get_client()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError:
        log.exception("Claude API call failed (model=%s)", model)
        return {}

    text = next((b.text for b in response.content if b.type == "text"), "")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned non-JSON output (model=%s): %r", model, text[:200])
        return {}


def _choose_model(content: str, long_form: bool) -> str:
    if long_form or len(content) > 2000:
        return settings.claude_sonnet_model
    return settings.claude_haiku_model


async def classify_signal(
    company_name: str,
    source_type: Literal["news_or_funding", "ats_job", "blog"],
    content: str,
    long_form: bool = False,
) -> dict[str, Any]:
    content = truncate(content, 6000)
    user = f'Company: "{company_name}"\nSource: {source_type}\n\nContent:\n{content}'
    result = await _invoke(
        SIGNAL_CLASSIFICATION_SYSTEM,
        user,
        model=_choose_model(content, long_form),
    )
    if "technologies_mentioned" in result:
        result["technologies_mentioned"] = [
            normalize_tech_name(t) for t in result.get("technologies_mentioned") or []
        ]
    return result


async def extract_stack(company_name: str, content: str) -> dict[str, Any]:
    content = truncate(content, 6000)
    user = f'Company: "{company_name}"\n\nJob content:\n{content}'
    result = await _invoke(STACK_EXTRACTION_SYSTEM, user, model=settings.claude_haiku_model)
    techs = result.get("technologies") or {}
    normalized: dict[str, float] = {}
    for name, conf in techs.items():
        if not isinstance(conf, (int, float)):
            continue
        normalized[normalize_tech_name(name)] = max(0.0, min(1.0, float(conf)))
    result["technologies"] = normalized
    return result


async def classify_hn_comment(comment_text: str) -> dict[str, Any]:
    content = truncate(comment_text, 4000)
    result = await _invoke(
        HN_COMMENT_SYSTEM,
        content,
        model=_choose_model(content, long_form=False),
    )
    if "technologies" in result:
        result["technologies"] = [normalize_tech_name(t) for t in result.get("technologies") or []]
    return result
