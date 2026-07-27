"""
storage.py — Data access layer for resume_bank.json.

All file I/O is isolated here so the rest of the app never touches the
JSON file directly.  Swap this module for a SQLite / Postgres
implementation later without changing any other file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PRIMARY = Path(__file__).parent / "resume_bank.json"
_FALLBACK = Path(__file__).parent / "resume_bank.example.json"
BANK_PATH = _PRIMARY if _PRIMARY.exists() else _FALLBACK


def load_bank() -> dict[str, Any]:
    """Load and return the full resume content bank as a dict."""
    with open(BANK_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_bank(data: dict[str, Any]) -> None:
    """Overwrite the resume content bank with *data*."""
    with open(BANK_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def get_all_keywords(bank: dict[str, Any]) -> set[str]:
    """
    Flatten every word/token found anywhere in the bank into a lowercase set.

    This is used by the fabrication-checker to confirm that every skill or
    tool Gemini mentions is traceable to something the user already claimed.
    """
    tokens: set[str] = set()

    def _harvest(obj: Any) -> None:
        if isinstance(obj, str):
            # Split on whitespace and common punctuation so multi-word
            # tokens like "AWS (EC2, S3…)" still contribute individual words.
            for word in re.split(r"[\s,;/()\[\]\"']+", obj):
                cleaned = word.strip(".").lower()
                if len(cleaned) > 1:
                    tokens.add(cleaned)
        elif isinstance(obj, dict):
            for v in obj.values():
                _harvest(v)
        elif isinstance(obj, list):
            for item in obj:
                _harvest(item)

    _harvest(bank)
    return tokens


def format_bank_to_text(bank: dict[str, Any]) -> str:
    """
    Format the structured resume bank JSON into a readable, detailed plain text
    document listing all contact details, skills, education, certifications,
    and bullet/summary variants so that Gemini can select from them.
    """
    lines: list[str] = []

    # Contact
    contact = bank.get("contact", {})
    if contact:
        lines.append(contact.get("name", "").upper())
        contact_info = []
        if contact.get("email"): contact_info.append(contact.get("email"))
        if contact.get("phone"): contact_info.append(contact.get("phone"))
        if contact.get("location"): contact_info.append(contact.get("location"))
        if contact_info:
            lines.append(" | ".join(contact_info))

        socials = []
        if contact.get("linkedin"): socials.append(f"LinkedIn: {contact.get('linkedin')}")
        if contact.get("github"): socials.append(f"GitHub: {contact.get('github')}")
        if contact.get("portfolio"): socials.append(f"Portfolio: {contact.get('portfolio')}")
        if socials:
            lines.append(" | ".join(socials))
        lines.append("")

    # Summary variants
    summaries = bank.get("summary_variants", [])
    if summaries:
        lines.append("PROFESSIONAL SUMMARY OPTIONS:")
        for idx, s in enumerate(summaries, 1):
            tags_str = f" [tags: {', '.join(s.get('tags', []))}]" if s.get("tags") else ""
            lines.append(f"- Option {idx}{tags_str}: {s.get('text', '')}")
        lines.append("")

    # Technical Skills
    skills = bank.get("skills", {})
    if skills:
        lines.append("TECHNICAL SKILLS:")
        for cat, items in skills.items():
            lines.append(f"- {cat}: {', '.join(items)}")
        lines.append("")

    # Work Experience
    internships = bank.get("internships", [])
    if internships:
        lines.append("WORK EXPERIENCE:")
        for i in internships:
            lines.append(f"{i.get('company', '')} - {i.get('role', '')} ({i.get('dates', '')})")
            bullets = i.get("bullet_variants", [])
            for b in bullets:
                tags_str = f" [tags: {', '.join(b.get('tags', []))}]" if b.get("tags") else ""
                lines.append(f"  * {b.get('text', '')}{tags_str}")
            lines.append("")

    # Projects
    projects = bank.get("projects", [])
    if projects:
        lines.append("PROJECTS:")
        for p in projects:
            lines.append(f"{p.get('name', '')} ({p.get('dates', '')})")
            if p.get("tech_stack"):
                lines.append(f"  Tech Stack: {p.get('tech_stack')}")
            if p.get("github_link"):
                lines.append(f"  GitHub: {p.get('github_link')}")
            if p.get("live_link"):
                lines.append(f"  Live Demo: {p.get('live_link')}")
            bullets = p.get("bullet_variants", [])
            for b in bullets:
                tags_str = f" [tags: {', '.join(b.get('tags', []))}]" if b.get("tags") else ""
                lines.append(f"  * {b.get('text', '')}{tags_str}")
            lines.append("")

    # Education
    education = bank.get("education", [])
    if education:
        lines.append("EDUCATION:")
        for e in education:
            gpa_str = f" (GPA: {e.get('gpa')})" if e.get("gpa") else ""
            lines.append(f"- {e.get('institution', '')} - {e.get('degree', '')} ({e.get('dates', '')}){gpa_str}")
            if e.get("relevant_coursework"):
                lines.append(f"  Coursework: {e.get('relevant_coursework')}")
        lines.append("")

    # Certifications
    certs = bank.get("certifications", [])
    if certs:
        lines.append("CERTIFICATIONS:")
        for c in certs:
            cred_str = f" (Credential ID: {c.get('credential_id')})" if c.get('credential_id') else ""
            lines.append(f"- {c.get('name', '')} - {c.get('issuer', '')} ({c.get('date', '')}){cred_str}")
        lines.append("")

    return "\n".join(lines)