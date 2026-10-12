"""Generates personalised cold emails using Claude Haiku.

Each call produces a ready-to-send email: salutation, body paragraphs, and
a signature line assembled from whatever profile fields the user has filled in.
The model picks the 3-5 most relevant highlights from the user's list rather
than dumping all of them, and explicitly addresses experience gaps when the
job states a requirement higher than the user's actual years.
"""
from __future__ import annotations

from app.config import settings
from app.models.user import User
from app.processors.llm_classifier import _invoke

_SYSTEM = """You write short, professional cold emails from a job-seeker to a recruiter or hiring manager.

Return JSON only, matching this schema exactly:
{
  "subject": "<concise subject line, ≤80 chars>",
  "body": "<full email text including salutation and signature>"
}

Rules:
- Salutation: use the recruiter first name if provided ("Hello Priya,"), otherwise "Hi [Company] Hiring Team,"
- Opening line: reference the specific job title if provided; if a stated experience requirement exceeds the user's years, acknowledge the gap in one sentence and immediately pivot to why the match is strong.
- Body: one tight paragraph about the user's background, then a bullet list of 3-5 highlights picked from the provided list that best match the job description. Do not list all highlights — curate.
- Location line: mention the user's location and remote comfort if location_text is set.
- Closing: "You can find more details in my attached resume." then a sign-off.
- Signature: name on one line, then phone (if set), then any links joined by " | " (LinkedIn | GitHub | Portfolio) — omit links that are null.
- Tone: direct, confident, no corporate filler. No "I hope this email finds you well."
- No markdown, no prose outside the JSON object."""


async def compose_cold_email(
    *,
    user: User,
    company_name: str,
    job_title: str | None,
    job_description: str | None,
    recruiter_name: str | None,
) -> dict[str, str]:
    """Call Claude Haiku to produce a personalised cold email.

    Returns ``{"subject": "...", "body": "..."}``; on API failure returns a
    minimal fallback dict so the client always has something to display.
    """
    exp_label = user.experience_label or (
        f"{user.experience_years}+ years" if user.experience_years else "several years"
    )

    sig_parts: list[str] = []
    if user.phone:
        sig_parts.append(user.phone)
    links = " | ".join(
        filter(None, [user.linkedin_url, user.github_url, user.portfolio_url])
    )
    if links:
        sig_parts.append(links)

    content_parts = [
        f"Recruiter first name: {recruiter_name or 'unknown (use company name)'}",
        f"Company: {company_name}",
        f"Job title: {job_title or 'not specified'}",
        f"User name: {user.name or 'the applicant'}",
        f"User experience: {exp_label}",
    ]

    if user.current_employer:
        content_parts.append(f"Current employer: {user.current_employer}")

    if user.location_text:
        content_parts.append(
            f"User location / remote: {user.location_text}, comfortable with remote work"
        )

    if user.highlights:
        content_parts.append(
            "Highlights (pick the 3-5 most relevant for this role):\n"
            + "\n".join(f"- {h}" for h in user.highlights)
        )

    if sig_parts:
        content_parts.append(
            "Signature (after name): " + "\n".join(sig_parts)
        )

    if job_description:
        # Truncate to avoid burning too many tokens on a long JD.
        jd = job_description[:3000]
        content_parts.append(f"\nJob description excerpt:\n{jd}")

    content = "\n".join(content_parts)

    result = await _invoke(
        _SYSTEM,
        content,
        model=settings.claude_haiku_model,
        max_tokens=1024,
    )

    if not result.get("subject") or not result.get("body"):
        # Fallback: return a minimal template so the UI never shows an empty sheet.
        greeting = f"Hello {recruiter_name}," if recruiter_name else f"Hi {company_name} Hiring Team,"
        role_ref = f"the {job_title} role" if job_title else "Flutter/mobile opportunities"
        fallback_body = (
            f"{greeting}\n\n"
            f"I'm writing to express my interest in {role_ref} at {company_name}. "
            f"I have {exp_label} of Flutter development experience and would love to discuss "
            f"how I can contribute to your team.\n\n"
            f"Please find my resume attached.\n\n"
            f"Best regards,\n{user.name or 'Applicant'}"
        )
        return {
            "subject": f"{job_title or 'Flutter Developer'} – {user.name or 'Application'}",
            "body": fallback_body,
        }

    return {"subject": result["subject"], "body": result["body"]}
