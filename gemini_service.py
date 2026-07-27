# -*- coding: utf-8 -*-
"""
gemini_service.py - Wraps the Google Gemini API call for resume tailoring.

Uses the current google-genai SDK (google.genai).
Single responsibility: send the content bank + JD to Gemini and return
a validated Python dict matching the tailored-resume schema.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import collections
from typing import Any
from debug_utils import save_json

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client setup
# ---------------------------------------------------------------------------

# Ordered list of known-working model names for automatic fallback
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"]

SYSTEM_INSTRUCTION = """You are an experienced Senior Technical Recruiter. Your job is to act as a professional resume tailoring assistant: extract contact details, build a semantic profile of the candidate, perform an intelligent semantic analysis of the Job Description (JD), select a dynamic resume strategy, and generate a tailored resume along with a scoring dashboard.

Follow these instructions strictly to ensure the tailored output is of the highest quality:

1. SOURCE OF TRUTH:
   - The uploaded master resume is the ONLY factual source.
   - You may rewrite, reorder, regroup, normalize, compress, improve wording, improve formatting, and tailor content.
   - You must NEVER: invent experience, invent projects, invent skills, invent certifications, invent education, invent technologies, invent metrics, invent achievements, invent responsibilities, invent company names, or invent dates.
   - Truthfulness always overrides ATS optimization.

2. PROFESSIONAL FORMATTING & ATS FRIENDLINESS:
   - Generate a clean, single-column, ATS-safe layout with consistent spacing and margins.
   - Use ATS-safe fonts (Calibri, Arial, Helvetica, Aptos, Carlito). Keep whitespace balanced.
   - Clickable hyperlinks for Name, Email, Phone, LinkedIn, GitHub, Portfolio (if present) must be preserved in the contact section.

3. DYNAMIC SECTION ORDER:
   - The order of sections should adapt dynamically to the candidate's experience level:
     * Typical fresher order: Header, Professional Summary, Technical Skills, Flagship Projects, Other Projects, Experience / Internships, Education, Certifications, Awards / Publications (if present).
     * Typical experienced order: Header, Professional Summary, Experience, Technical Skills, Projects, Education, Certifications.

4. PROFESSIONAL SUMMARY:
   - Generate a brand-new professional summary under 4-5 lines maximum for every JD.
   - Open immediately with the candidate's actual professional identity and key expertise. Avoid generic buzzwords or exaggerated marketing language (e.g., 'Highly motivated', 'Results-driven', 'Passionate', 'Dynamic individual', 'Proven expert', 'World-class', 'Exceptional leader', 'Highly accomplished').
   - Prefer factual, realistic language based on the uploaded resume (e.g. 'Demonstrated experience in...', 'Experience developing...', 'Strong foundation in...', 'Hands-on experience with...', 'Familiar with...', 'Built...', 'Implemented...').
   - Ensure sentences flow naturally, avoiding repetitive phrasing, robotic transitions, or unnecessary filler.

5. TECHNICAL SKILLS:
   - Preserve every verified skill. Never invent or remove technical skills.
   - Group technologies into recruiter-friendly, specific categories whenever appropriate (e.g., Programming Languages, Backend & APIs, Databases, Cloud & DevOps, Frontend, Data & AI) rather than combining unrelated technologies under broad headings like 'Languages & Frameworks'.
   - The skills_selected section must contain ONLY concrete technical tools, languages, frameworks, platforms, and named technologies. Never include job-duty phrases, QA methodology terms, or process descriptions (e.g., 'Manual Testing', 'Regression Testing', 'Bug Tracking', 'Defect Documentation', 'Log Analysis', 'Troubleshooting', 'Functional Tests', 'SDLC') in skills_selected — these belong in bullet points only.

6. PROJECTS:
   - Never delete projects. Every project from the uploaded master resume must remain (though they can be reordered).
   - Project names and technologies must never change. Wording of bullets may be rewritten professionally.
   - Present project technologies consistently under a 'Tech Stack: Python • Flask • Docker • SQLite' header with a consistent separator.

7. EXPERIENCE / INTERNSHIPS:
   - Every experience and internship entry must remain. Do not omit, delete, or merge entries.
   - Chronology always wins: order experience chronologically with the newest first and oldest last. Do not reorder by relevance.

8. EDUCATION:
   - Education is factual and must never be tailored or deleted. All entries from the uploaded resume must remain.
   - Order chronologically with the highest/most recent qualification first.
   - For Bachelor's, Master's, PhD, Diploma, or equivalent university/college degrees, represent scores exactly as CGPA: X.XX / 10.00 using the factual value from the master resume.
   - For school-level degrees/certificates (HSC, SSC, XII, X, Matriculation, Secondary School, High School), mention scores exactly as Score: XX% using the factual value from the master resume. Do not prepend extra duplicate labels. Never convert or fabricate scores.

9. CERTIFICATIONS:
   - Every certification must remain. Never delete, replace, or summarize certifications. Reorder only if needed. Certification names, issuers, and dates must remain unchanged.

10. RECRUITER WRITING STYLE & SPACE MANAGEMENT:
    - Lead bullets with strong action verbs. Rotate starting verbs naturally. Use active voice exclusively.
    - Adapt verb selection and technical scope strictly to the candidate's actual experience level (dynamically inferred from the master resume):
      * For students, freshers, interns, graduates, or entry-level engineers: avoid verbs that imply executive ownership, enterprise-wide architecture, or senior technical leadership (e.g., 'Architected', 'Spearheaded', 'Championed', 'Revolutionized', 'Directed', 'Led enterprise-wide', 'Defined organization-wide strategy') unless explicitly supported by the uploaded resume. Use realistic professional verbs (e.g., 'Developed', 'Designed', 'Implemented', 'Built', 'Created', 'Engineered', 'Integrated', 'Configured', 'Optimized', 'Tested', 'Validated', 'Enhanced', 'Automated', 'Maintained', 'Improved').
      * For experienced professionals: use stronger verbs only when supported by the original resume. Never exaggerate responsibilities.
    - Ensure appropriate technical scope: the wording should accurately represent the scope of the candidate's work and avoid language that unintentionally inflates responsibility (prefer wording reflecting implementation, development, testing, deployment, or collaboration unless the uploaded resume clearly demonstrates ownership of architecture, organizational strategy, or technical leadership).
    - Maintain absolute terminology, plurality, capitalization, and naming convention consistency across the entire resume (e.g., do not mix 'REST APIs' and 'REST API', or 'Functional Testing' and 'Manual Functional Testing' unless context requires it).
    - Focus on outcomes/purpose, but never fabricate metrics.
    - Each bullet should occupy approximately two lines maximum in the final PDF (target: 18-25 words).
    - If the resume exceeds target length, shorten bullets, remove redundant wording, merge repetitive bullet descriptions, and tighten formatting. Do not delete factual sections or entries unless explicitly requested.

11. ATS OPTIMIZATION & TERMINOLOGY:
    - Prefer standard technical terminology commonly used by recruiters, hiring managers, and engineering teams (e.g., 'REST APIs' instead of 'REST API', 'Web Applications' instead of 'Web Application', 'Backend Services' instead of 'Backend Service', 'Cloud Platforms' instead of 'Cloud Platform' when multiple technologies are involved). Choose terminology naturally according to context.
    - Integrate JD keywords naturally only where they genuinely match the candidate's experience. Never keyword stuff or insert keywords simply to inflate ATS scores. Use semantic equivalents and map concepts intelligently.

12. RESUME SCORING DASHBOARD:
    - Assess the final tailored resume against the JD to generate realistic scores and professional feedback:
      * "ats_score": Integer (0-100) based on clean formatting (no tables, single column, machine-readability).
      * "ats_explanation": Clear rationale for the ATS score.
      * "readability_score": Integer (0-100) based on bullet quality, active verbs, flow, and word count.
      * "readability_explanation": Clear rationale for readability.
      * "match_score": Integer (0-100) representing true capability fit against the prioritized JD requirements.
      * "match_explanation": Clear rationale for match score.
      * "keyword_coverage": Integer (0-100) percentage of selected keywords integrated.
      * "missing_skills": List of important skills from the JD missing in the candidate's profile.
      * "weaknesses": List of potential weaknesses in the candidate's match profile.
      * "strengths": List of candidate's strongest matching points.
      * "improvements": List of actionable improvement suggestions.

Return ONLY a valid JSON object matching this exact schema — no markdown, no prose, no code fences:
{
  "tailored_resume": {
    "contact": {
      "name": "<string>",
      "location": "<string>",
      "email": "<string>",
      "phone": "<string>",
      "linkedin": "<string>",
      "github": "<string>",
      "portfolio": "<string>"
    },
    "summary": "<string>",
    "skills_selected": [{"category": "<string>", "items": ["<string>"]}],
    "flagship_projects_selected": [
      {
        "name": "<string>",
        "dates": "<string>",
        "tech_stack": "<string>",
        "github_link": "<string>",
        "live_demo": "<string>",
        "bullets": ["<string>"]
      }
    ],
    "other_projects_selected": [
      {
        "name": "<string>",
        "dates": "<string>",
        "tech_stack": "<string>",
        "github_link": "<string>",
        "live_demo": "<string>",
        "bullets": ["<string>"]
      }
    ],
    "internships_selected": [
      {
        "company": "<string>",
        "role": "<string>",
        "dates": "<string>",
        "bullets": ["<string>"]
      }
    ],
    "education": [
      {
        "institution": "<string>",
        "degree": "<string>",
        "dates": "<string>",
        "gpa": "<string>",
        "relevant_coursework": "<string>"
      }
    ],
    "certifications": [
      {
        "name": "<string>",
        "issuer": "<string>",
        "date": "<string>"
      }
    ],
    "publications": [
      {
        "title": "<string>",
        "publisher": "<string>",
        "date": "<string>",
        "doi": "<string>",
        "url": "<string>"
      }
    ]
  },
  "dashboard": {
    "ats_score": <int>,
    "ats_explanation": "<string>",
    "readability_score": <int>,
    "readability_explanation": "<string>",
    "match_score": <int>,
    "match_explanation": "<string>",
    "keyword_coverage": <int>,
    "missing_skills": ["<string>"],
    "weaknesses": ["<string>"],
    "strengths": ["<string>"],
    "improvements": ["<string>"]
  }
}"""



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _generate_fallback_dashboard(tailored: dict[str, Any], jd_text: str) -> dict[str, Any]:
    """Generates a fallback dashboard analysis in case the model does not return one."""
    return {
        "ats_score": 85,
        "ats_explanation": "Single-column format, standard section headings, and machine-readable text structures ensure high ATS compatibility.",
        "readability_score": 80,
        "readability_explanation": "Action-oriented bullet points starting with strong verbs provide clear readability for recruiters.",
        "match_score": 75,
        "match_explanation": "Factual experiences align moderately well with the core responsibilities of the role.",
        "keyword_coverage": 70,
        "missing_skills": [],
        "weaknesses": ["Preferred tools or secondary frameworks not explicitly found in the master resume."],
        "strengths": ["Strong foundational background relevant to the key role description."],
        "improvements": ["Consider highlighting quantifiable metrics for completed project bullets."]
    }


MASTER_ENTRY_DATE_RANGE_PATTERN = (
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4}'
    r'\s*(?:[-â€“â€”]|to)\s*'
    r'(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4})'
)

MASTER_ENTRY_SECTION_HEADERS = [
    "professional summary", "summary", "technical skills", "skills",
    "projects", "flagship projects", "other projects", "personal projects",
    "internship experience", "internships", "work experience", "experience",
    "employment", "professional experience", "education", "certifications",
    "publications"
]


def count_master_resume_entries(master_resume: str, section_keyword: str) -> int:
    lines = master_resume.splitlines()
    save_json("master_resume_lines.json", {"lines": lines})
    found_section = False
    section_lines = []

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        line_lower = line_strip.lower()

        if not found_section:
            if (
                line_lower == section_keyword
                or line_lower.rstrip(":") == section_keyword
                or (line_strip.isupper() and section_keyword in line_lower)
            ):
                found_section = True
                continue

        is_header = False
        for header in MASTER_ENTRY_SECTION_HEADERS:
            if line_lower == header or line_lower.rstrip(":") == header:
                if header != section_keyword:
                    is_header = True
                    break
        if is_header:
            break

        if line_strip.isupper() and any(
            h in line_lower for h in
            ["education", "experience", "projects", "skills",
             "publications", "certifications", "internship"]
        ) and section_keyword not in line_lower:
            break

        section_lines.append(line_strip)

    section_text = "\n".join(section_lines)
    save_json(
        f"debug_section_{section_keyword}.json",
        {
            "section": section_keyword,
            "lines": section_lines,
            "text": section_text,
        },
    )

    date_matches = re.findall(MASTER_ENTRY_DATE_RANGE_PATTERN, section_text, flags=re.IGNORECASE)
    if date_matches:
        return len(date_matches)
    bullet_lines = [
        line for line in section_lines
        if line.startswith(("-", "*", "â€¢"))
    ]
    if bullet_lines:
        return len(bullet_lines)

    return len([line for line in section_lines if line])


def get_master_resume_entry_counts(master_resume: str) -> dict[str, int]:
    internships_count = max(
        count_master_resume_entries(master_resume, "internship"),
        count_master_resume_entries(master_resume, "experience"),
        count_master_resume_entries(master_resume, "employment"),
    )
    return {
        "projects": count_master_resume_entries(master_resume, "projects"),
        "internships": internships_count,
        "education": count_master_resume_entries(master_resume, "education"),
        "certifications": count_master_resume_entries(master_resume, "certifications"),
        "publications": count_master_resume_entries(master_resume, "publications"),
    }


MASTER_REPAIR_DATE_RANGE_PATTERN = (
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4}\b'
    r'.{0,12}?'
    r'\b(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4})\b'
)

MASTER_REPAIR_URL_PATTERN = r'(?:https?://)?(?:www\.)?[\w.-]+\.(?:com|in|io|app|dev|org|net)[^\s,;)]*'


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r'https?://', '', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _field_text(entry: dict[str, Any], fields: list[str]) -> str:
    return " ".join(str(entry.get(field, "")) for field in fields if entry.get(field))


def _clean_entry_line(line: str) -> str:
    line = re.sub(r'^\s*(?:\d+[\.)]\s*|[-*•]\s*)', '', line).strip()
    return re.sub(r'\s+', ' ', line).strip()


def _strip_date_range(text: str) -> str:
    text = re.sub(MASTER_REPAIR_DATE_RANGE_PATTERN, '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\s+', ' ', text)
    return re.sub(r'\s*[-–—,|]+\s*$', '', text).strip()


def _extract_first_date_range(text: str) -> str:
    match = re.search(MASTER_REPAIR_DATE_RANGE_PATTERN, text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r'\s+', ' ', match.group(0)).strip() if match else ""


def _extract_urls(text: str) -> list[str]:
    urls = []
    for match in re.findall(MASTER_REPAIR_URL_PATTERN, text, flags=re.IGNORECASE):
        clean = match.strip().rstrip(".,;)")
        if clean and clean.lower() not in [u.lower() for u in urls]:
            urls.append(clean)
    return urls


def _extract_master_section_lines(master_resume: str, section_keywords: list[str]) -> list[str]:
    lines = master_resume.splitlines()
    found_section = False
    section_lines: list[str] = []
    lowered_keywords = [kw.lower() for kw in section_keywords]

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        line_lower = line.lower().rstrip(":")

        if not found_section:
            if line_lower in lowered_keywords or (
                line.isupper() and any(kw in line_lower for kw in lowered_keywords)
            ):
                found_section = True
            continue

        is_next_header = False
        for header in MASTER_ENTRY_SECTION_HEADERS:
            if line_lower == header or line_lower.rstrip(":") == header:
                if not any(header == kw or kw in header for kw in lowered_keywords):
                    is_next_header = True
                    break
        if is_next_header:
            break

        if line.isupper() and any(
            h in line_lower for h in
            ["summary", "skills", "projects", "experience", "internship", "education", "certifications", "publications"]
        ) and not any(kw in line_lower for kw in lowered_keywords):
            break

        section_lines.append(line)

    return section_lines


def _split_numbered_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.match(r'^\s*\d+[\.)]\s+', line) and current:
            entries.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append(current)
    return entries


def _split_dated_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []
    current_has_date = False

    for line in lines:
        line_has_date = bool(re.search(MASTER_REPAIR_DATE_RANGE_PATTERN, line, flags=re.IGNORECASE | re.DOTALL))
        starts_bullet = bool(re.match(r'^\s*[-*•]', line))

        if line_has_date and current and current_has_date and not starts_bullet:
            entries.append(current)
            current = [line]
            current_has_date = True
        else:
            current.append(line)
            current_has_date = current_has_date or line_has_date

    if current:
        entries.append(current)
    return entries


def _split_bulleted_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        starts_bullet = bool(re.match(r'^\s*[-*•]', line))
        if starts_bullet and current:
            entries.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        entries.append(current)
    return entries


def _entry_bullets(lines: list[str]) -> list[str]:
    bullets = []
    seen_first_bullet = False
    for line in lines:
        if re.match(r'^\s*[-*•]', line):
            bullets.append(_clean_entry_line(line))
            seen_first_bullet = True
        elif seen_first_bullet and bullets:
            bullets[-1] = f"{bullets[-1]} {_clean_entry_line(line)}".strip()
    return [re.sub(r'\s+', ' ', bullet).strip() for bullet in bullets if bullet.strip()]


def _entry_pre_bullet_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if re.match(r'^\s*[-*•]', line):
            break
        result.append(line)
    return result


def _entry_non_bullet_lines(lines: list[str]) -> list[str]:
    return [_clean_entry_line(line) for line in _entry_pre_bullet_lines(lines)]


def _parse_project_entry(lines: list[str]) -> dict[str, Any]:
    text = " ".join(_clean_entry_line(line) for line in lines)
    dates = _extract_first_date_range(text)
    non_bullets = _entry_non_bullet_lines(lines)

    header_parts = []
    for line in non_bullets:
        header_parts.append(line)
        if re.search(MASTER_REPAIR_DATE_RANGE_PATTERN, line, flags=re.IGNORECASE | re.DOTALL):
            break

    header = _strip_date_range(" ".join(header_parts))
    remaining_non_bullets = non_bullets[len(header_parts):]
    tech_stack = remaining_non_bullets[0] if remaining_non_bullets else ""
    urls = _extract_urls(text)
    github_link = next((url for url in urls if "github" in url.lower()), "")
    live_link = next((url for url in urls if "github" not in url.lower()), "")

    project = {
        "name": header,
        "dates": dates,
        "tech_stack": re.sub(r'\s*\|\s*(GitHub|Live|URL|Demo):.*$', '', tech_stack, flags=re.IGNORECASE).strip(),
        "github_link": github_link,
        "bullets": _entry_bullets(lines),
        "section": "Other Projects",
        "source": "master_resume_repair",
    }
    if live_link:
        project["live_demo"] = live_link
    return project


def _parse_internship_entry(lines: list[str]) -> dict[str, Any]:
    text = " ".join(_clean_entry_line(line) for line in lines)
    dates = _extract_first_date_range(text)
    header = _strip_date_range(_entry_non_bullet_lines(lines)[0] if _entry_non_bullet_lines(lines) else text)
    parts = re.split(r'\s+[-–—]\s+', header, maxsplit=1)
    if len(parts) == 2:
        role, company = parts[0].strip(), parts[1].strip()
    else:
        role, company = header.strip(), ""

    return {
        "company": company,
        "role": role,
        "dates": dates,
        "bullets": _entry_bullets(lines),
        "source": "master_resume_repair",
    }


def _parse_education_entry(lines: list[str]) -> dict[str, Any]:
    non_bullets = _entry_non_bullet_lines(lines)
    text = " ".join(non_bullets)
    dates = _extract_first_date_range(text)
    degree = _strip_date_range(non_bullets[0] if non_bullets else text)
    institution_line = non_bullets[1] if len(non_bullets) > 1 else ""
    institution = institution_line.split("|")[0].strip()
    gpa = ""
    gpa_match = re.search(r'(?:CGPA|Score)\s*:?\s*([0-9.]+\s*(?:/\s*10(?:\.00)?|%)?)', text, flags=re.IGNORECASE)
    if gpa_match:
        gpa = gpa_match.group(1).strip()

    return {
        "institution": institution,
        "degree": degree,
        "dates": dates,
        "gpa": gpa,
        "relevant_coursework": "",
        "source": "master_resume_repair",
    }


def _parse_certification_entry(lines: list[str]) -> dict[str, Any]:
    text = " ".join(_clean_entry_line(line) for line in lines)
    date = ""
    date_match = re.search(r'\(([^)]*\d{4}[^)]*)\)', text)
    if date_match:
        date = date_match.group(1).strip()
        text = text[:date_match.start()] + text[date_match.end():]
    parts = re.split(r'\s+[-–—]\s+', text, maxsplit=1)
    name = parts[0].strip()
    issuer = parts[1].strip() if len(parts) == 2 else ""
    return {"name": name, "issuer": issuer, "date": date, "source": "master_resume_repair"}


def _parse_publication_entry(lines: list[str]) -> dict[str, Any]:
    text = " ".join(_clean_entry_line(line) for line in lines)
    doi_match = re.search(r'\bDOI\s*:?\s*([^\s]+)', text, flags=re.IGNORECASE)
    doi = doi_match.group(1).strip().rstrip(".,;") if doi_match else ""
    urls = _extract_urls(text)
    date_match = re.search(
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)\s+\d{4}\b',
        text,
        flags=re.IGNORECASE,
    )
    date = date_match.group(0).strip() if date_match else ""
    title = re.split(r'\s+[-–—]\s+', text, maxsplit=1)[0].strip()
    publisher = text[len(title):].strip(" -–—")
    if doi_match:
        publisher = publisher[:doi_match.start() - len(title)].strip(" -–—.,")
    return {
        "title": title,
        "publisher": publisher,
        "date": date,
        "doi": doi,
        "url": urls[0] if urls else "",
        "source": "master_resume_repair",
    }


def parse_master_resume_entries(master_resume: str) -> dict[str, list[dict[str, Any]]]:
    project_lines = _extract_master_section_lines(master_resume, ["projects", "flagship projects", "other projects"])
    project_groups = _split_numbered_entries(project_lines)
    if len(project_groups) <= 1:
        project_groups = _split_dated_entries(project_lines)

    internship_lines = _extract_master_section_lines(
        master_resume,
        ["internship experience", "internships", "work experience", "experience", "employment", "professional experience"],
    )
    education_lines = _extract_master_section_lines(master_resume, ["education"])
    certification_lines = _extract_master_section_lines(master_resume, ["certifications"])
    publication_lines = _extract_master_section_lines(master_resume, ["publications"])

    parsed = {
        "projects": [_parse_project_entry(group) for group in project_groups],
        "internships": [_parse_internship_entry(group) for group in _split_dated_entries(internship_lines)],
        "education": [_parse_education_entry(group) for group in _split_dated_entries(education_lines)],
        "certifications": [_parse_certification_entry(group) for group in _split_bulleted_entries(certification_lines)],
        "publications": [_parse_publication_entry(group) for group in _split_bulleted_entries(publication_lines)],
    }
    return {
        key: [entry for entry in entries if any(str(v).strip() for k, v in entry.items() if k != "source")]
        for key, entries in parsed.items()
    }


def _entry_identity(entry: dict[str, Any], section: str) -> str:
    if section == "projects":
        return _field_text(entry, ["name"])
    if section == "internships":
        return _field_text(entry, ["role", "company"])
    if section == "education":
        return _field_text(entry, ["degree", "institution"])
    if section == "certifications":
        return _field_text(entry, ["name", "issuer"])
    if section == "publications":
        return _field_text(entry, ["title"])
    return " ".join(str(v) for v in entry.values())


def _entries_match(master_entry: dict[str, Any], generated_entry: dict[str, Any], section: str) -> bool:
    master_id = _normalize_match_text(_entry_identity(master_entry, section))
    generated_id = _normalize_match_text(_entry_identity(generated_entry, section))
    if not master_id or not generated_id:
        return False

    if master_id in generated_id or generated_id in master_id:
        return True

    master_date = _normalize_match_text(master_entry.get("dates") or master_entry.get("date"))
    generated_date = _normalize_match_text(generated_entry.get("dates") or generated_entry.get("date"))
    master_numbers = set(re.findall(r'\d+', master_id))
    generated_numbers = set(re.findall(r'\d+', generated_id))
    if master_numbers and generated_numbers and master_numbers != generated_numbers:
        return False

    master_tokens = {tok for tok in master_id.split() if len(tok) > 2 or tok.isdigit()}
    generated_tokens = {tok for tok in generated_id.split() if len(tok) > 2 or tok.isdigit()}
    overlap = master_tokens & generated_tokens
    if not master_tokens or not generated_tokens:
        return False

    # For certifications: use a lower overlap threshold since cert names
    # often get slightly reworded by Gemini (e.g. "OCI" vs "Oracle Cloud
    # Infrastructure"). Match if at least 40% of the shorter name's tokens
    # overlap — much more forgiving than the default which requires 3-4 tokens.
    if section == "education":
        master_date = _normalize_match_text(master_entry.get("dates", ""))
        generated_date = _normalize_match_text(generated_entry.get("dates", ""))
        if master_date and generated_date and master_date == generated_date:
            return True
        return False

    if section == "certifications":
        shorter_len = min(len(master_tokens), len(generated_tokens))
        if shorter_len > 0:
            overlap_ratio = len(overlap) / shorter_len
            if overlap_ratio >= 0.4:
                return True
        return False

    required_overlap = 1 if section in {"publications"} else max(2, min(len(master_tokens), len(generated_tokens), 4) - 1)
    if len(overlap) >= required_overlap:
        if not master_date or not generated_date or master_date == generated_date:
            return True

    return False


def _append_missing_entries(
    resume: dict[str, Any],
    section_name: str,
    target_key: str,
    master_entries: list[dict[str, Any]],
) -> int:
    existing = resume.get(target_key)
    if not isinstance(existing, list):
        existing = []
        resume[target_key] = existing

    added = 0
    for master_entry in master_entries:
        if any(isinstance(item, dict) and _entries_match(master_entry, item, section_name) for item in existing):
            continue
        repaired_entry = dict(master_entry)
        existing.append(repaired_entry)
        added += 1
    return added


def repair_tailored_resume_from_master(tailored_data: dict[str, Any], master_resume: str) -> dict[str, int]:
    if not isinstance(tailored_data.get("tailored_resume"), dict):
        return {}

    resume = tailored_data["tailored_resume"]
    master_entries = parse_master_resume_entries(master_resume)

    added_counts = {
        "projects": _append_missing_entries(resume, "projects", "projects", master_entries.get("projects", [])),
        "internships_selected": _append_missing_entries(resume, "internships", "internships_selected", master_entries.get("internships", [])),
        "education": _append_missing_entries(resume, "education", "education", master_entries.get("education", [])),
        "certifications": _append_missing_entries(resume, "certifications", "certifications", master_entries.get("certifications", [])),
        "publications": _append_missing_entries(resume, "publications", "publications", master_entries.get("publications", [])),
    }

    if resume.get("projects"):
        resume["projects_selected"] = resume["projects"]
    if "section_order" not in resume or not isinstance(resume["section_order"], list):
        resume["section_order"] = ["summary", "skills", "projects", "internships", "education", "certifications", "publications"]
    else:
        for section in ["projects", "internships", "education", "certifications", "publications"]:
            if resume.get(section if section != "internships" else "internships_selected") and section not in resume["section_order"]:
                resume["section_order"].append(section)
    if "section_titles" not in resume or not isinstance(resume["section_titles"], dict):
        resume["section_titles"] = {}
    resume["section_titles"].setdefault("publications", "Publications")
    resume["section_titles"].setdefault("certifications", "Certifications")

    added_counts = {key: value for key, value in added_counts.items() if value}
    if added_counts:
        logger.warning("Deterministic master-resume repair appended missing entries before validation: %s", added_counts)
    return added_counts


def generate_tailored_resume(master_resume: str, jd_text: str, selected_keywords: list[str] | None = None) -> dict[str, Any]:
    """
    Call Gemini once or twice to tailor the resume.
    """
    from google import genai
    from google.genai import types as genai_types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Add it to your .env file and restart the server."
        )

    client = genai.Client(api_key=api_key)

    keywords_instruction = ""
    if selected_keywords:
        kw_list = ", ".join(selected_keywords)
        keywords_instruction = (
            f"\n\nUSER-SELECTED KEYWORDS TO INTEGRATE: {kw_list}\n"
            "Integrate these keywords naturally where appropriate."
        )

    master_entry_counts = get_master_resume_entry_counts(master_resume)
    entry_count_instruction = f"""

---

MASTER RESUME ENTRY COUNTS - HARD PRESERVATION REQUIREMENT

Projects: {master_entry_counts["projects"]}
Internships / Experience: {master_entry_counts["internships"]}
Education: {master_entry_counts["education"]}
Certifications: {master_entry_counts["certifications"]}
Publications: {master_entry_counts["publications"]}

Return EXACTLY these counts in the JSON output. Do not omit entries. Do not merge entries. Do not summarize multiple entries into one item. Do not prioritize only the most relevant entries.

Project count is the combined total across flagship_projects_selected and other_projects_selected. Each master project must appear once, and only once.

CERTIFICATIONS ARE FACTUAL RECORDS — never drop, merge, or omit any certification entry. The certifications list must contain EXACTLY {master_entry_counts["certifications"]} entries matching the master resume. Dropping even one certification is a critical error. Copy every certification name, issuer, and date exactly as they appear in the master resume.

If a count is 0, return an empty list for that section. If a count is greater than 0, every master resume entry for that section must appear in the matching JSON list.
"""

    prompt = f"""Below is the candidate's complete master resume content (raw text):

{master_resume}

---

Job Description:
{jd_text}
{keywords_instruction}

---

Using ONLY the facts and experiences present in the master resume above, produce a tailored resume and dashboard JSON matching the schema in your system instructions.

Follow the schema exactly.

Write professional, high-impact, active-voice descriptions.

Do not add any markdown formatting or prose outside the JSON object.
""" 

    feedback_instruction = ""
    last_errors = []
    parsed_data = None

    for attempt in range(4):
        current_prompt = prompt
        current_prompt += entry_count_instruction
        if feedback_instruction:
            current_prompt += (
                f"\n\n⚠️ PREVIOUS ATTEMPT REJECTED due to validation issues. Please fix these:\n{feedback_instruction}\n"
                f"\nCRITICAL REMINDERS:\n"
                f"1. You MUST NOT repeat any of the rejected buzzwords, clichés, or format errors in your response.\n"
                f"2. You MUST preserve all entries (projects, internships, education, certifications, publications) from the master resume. Do not truncate, merge, prioritize, or omit any entries.\n"
                f"3. Return the complete corrected JSON."
            )

        # Escalate temperature progressively: 0.2 -> 0.7 -> 0.85 -> 1.0
        temperatures = [0.2, 0.7, 0.85, 1.0]
        temp = temperatures[attempt]

        try:
            response = generate_content_with_fallback(
                client=client,
                prompt=current_prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=temp
            )
            raw_text = response.text
            logger.info("Received Gemini response (%d chars) on attempt %d with temp %.2f.", len(raw_text), attempt + 1, temp)
            
            # Parse response JSON
            cleaned = _strip_markdown_fences(raw_text)
            parsed_data = json.loads(cleaned)

            save_json("01_raw_gemini.json", parsed_data)


            # Inject fallback dashboard if missing/malformed

            if not isinstance(parsed_data.get("dashboard"), dict):
                parsed_data["dashboard"] = {
                    "ats_score": 80,
                    "ats_explanation": "Resume format and layout optimized for ATS readability.",
                    "readability_score": 80,
                    "readability_explanation": "Concise bullet points and active phrasing improve readability.",
                    "match_score": 75,
                    "match_explanation": "Experience tailored to meet key requirements from the JD.",
                    "keyword_coverage": 70,
                    "missing_skills": [],
                    "weaknesses": [],
                    "strengths": ["Clear alignment with target role"],
                    "improvements": []
                }
                parsed_data["dashboard_fallback_used"] = True

            # Normalize and supplement tailored_resume keys to match schema expectations
            if "tailored_resume" in parsed_data and isinstance(parsed_data["tailored_resume"], dict):
                resume = parsed_data["tailored_resume"]
                
                # 1. Map flagship/other projects to projects list
                if "projects" not in resume:
                    projects = []
                    for p in resume.get("flagship_projects_selected", []):
                        if isinstance(p, dict):
                            p["section"] = "Flagship Projects"
                            projects.append(p)
                    for p in resume.get("other_projects_selected", []):
                        if isinstance(p, dict):
                            p["section"] = "Other Projects"
                            projects.append(p)
                    if not projects and "projects_selected" in resume:
                        projects = resume["projects_selected"]
                    resume["projects"] = projects

                # 2. Normalize section_order to match template expectations
                if "section_order" not in resume or not isinstance(resume["section_order"], list):
                    resume["section_order"] = ["summary", "skills", "projects", "internships", "education", "certifications", "publications"]
                else:
                    raw_order = resume["section_order"]
                    normalized_order = []
                    for sec in raw_order:
                        if not isinstance(sec, str):
                            continue
                        sec_lower = sec.lower().strip()
                        if sec_lower in ("skills_selected", "skills", "technical skills"):
                            normalized_order.append("skills")
                        elif sec_lower in ("internships_selected", "internships", "experience", "work experience", "professional experience"):
                            normalized_order.append("internships")
                        elif sec_lower in ("flagship_projects_selected", "other_projects_selected", "projects", "projects_selected"):
                            normalized_order.append("projects")
                        else:
                            normalized_order.append(sec_lower)
                    resume["section_order"] = normalized_order

                # 3. Normalize section_titles
                if "section_titles" not in resume or not isinstance(resume["section_titles"], dict):
                    resume["section_titles"] = {
                        "summary": "Professional Summary",
                        "skills": "Technical Skills",
                        "projects": "Projects",
                        "internships": "Experience",
                        "education": "Education",
                        "certifications": "Certifications",
                        "publications": "Publications"
                    }
            
            # Run LLM-based classification to filter non-technical skill/activity phrases before validation
            filter_non_skills_via_classification(client, parsed_data, selected_keywords)

            # Deterministically restore any factual entries Gemini omitted before validation.
            repair_tailored_resume_from_master(parsed_data, master_resume)

            # Strip hallucinated coursework and other fabricated content.
            if isinstance(parsed_data.get("tailored_resume"), dict):
                parsed_data["tailored_resume"] = clean_tailored_resume(
                    parsed_data["tailored_resume"], master_resume
                )

            save_json("02_after_repair.json", parsed_data)
            
            # Validate
            errors, unverified_items = validate_tailored_resume(parsed_data, master_resume, selected_keywords, return_unverified=True)
            if not errors:
                logger.info("Tailored resume passed validation on attempt %d.", attempt + 1)
                if "tailored_resume" in parsed_data and "skills_selected" in parsed_data["tailored_resume"]:
                    parsed_data["tailored_resume"]["skills_selected"] = deduplicate_skills_selected(
                        parsed_data["tailored_resume"]["skills_selected"]
                    )
                parsed_data["unverified_skills"] = unverified_items
                return parsed_data
            else:
                logger.warning("Attempt %d validation failed: %s", attempt + 1, errors)
                last_errors = errors
                
                # Check if we should stop retrying early (non-buzzword failure limit of 2 attempts)
                is_buzzword_only = all("banned buzzword phrase" in err for err in errors)
                if attempt >= 1 and not is_buzzword_only:
                    logger.info("Stopping retry loop early (attempt %d): non-buzzword errors present: %s", attempt + 1, errors)
                    break
                    
                # Format feedback instruction for next retry
                feedback_instruction = "\n".join(f"- {err}" for err in errors)

                # Append alternative phrasing suggestions specifically for buzzwords
                buzzword_errors = [err for err in errors if "banned buzzword phrase" in err]
                if buzzword_errors:
                    suggestions_list = []
                    for err in buzzword_errors:
                        match = re.search(r"banned buzzword phrase '([^']+)'", err)
                        if match:
                            phrase = match.group(1)
                            sug = get_buzzword_suggestions(phrase)
                            suggestions_list.append(f"For '{phrase}':\n{sug}")
                    if suggestions_list:
                        feedback_instruction += "\n\n💡 Alternative Phrasing Suggestions:\n" + "\n\n".join(suggestions_list)

                # For missing keyword errors, extract the missing keywords and give
                # explicit placement guidance so Gemini knows to use bullets/summary
                # rather than trying to add them to the skills section (where the
                # classifier will strip them anyway).
                keyword_errors = [err for err in errors if "Missing user-selected keywords" in err]
                if keyword_errors:
                    missing_kws = []
                    for err in keyword_errors:
                        match = re.search(r"completely missing from the generated resume: (.+?)\.", err)
                        if match:
                            kws = [k.strip() for k in match.group(1).split(",") if k.strip()]
                            missing_kws.extend(kws)

                    if missing_kws:
                        kw_guidance_lines = []
                        for kw in missing_kws:
                            kw_lower = kw.lower()
                            if any(term in kw_lower for term in ["testing", "test", "qa", "quality"]):
                                kw_guidance_lines.append(
                                    f"- '{kw}': Add naturally to a project or internship bullet "
                                    f"(e.g. 'Conducted {kw.lower()} to validate...' or "
                                    f"'Performed {kw.lower()} across...'). DO NOT add to skills section."
                                )
                            elif any(term in kw_lower for term in ["bug", "defect", "issue", "tracking", "documentation"]):
                                kw_guidance_lines.append(
                                    f"- '{kw}': Add to a project or internship bullet "
                                    f"(e.g. 'Maintained {kw.lower()} system to...' or "
                                    f"'Utilized {kw.lower()} to track...'). DO NOT add to skills section."
                                )
                            elif any(term in kw_lower for term in ["log", "analysis", "troubleshoot", "debug"]):
                                kw_guidance_lines.append(
                                    f"- '{kw}': Weave into a project bullet "
                                    f"(e.g. 'Performed {kw.lower()} to identify...'). DO NOT add to skills section."
                                )
                            elif any(term in kw_lower for term in ["wireless", "specification", "protocol", "standard"]):
                                kw_guidance_lines.append(
                                    f"- '{kw}': Add to the professional summary or a relevant project bullet "
                                    f"(e.g. 'interpreted {kw.lower()} to...' or "
                                    f"'validated system against {kw.lower()}'). DO NOT add to skills section."
                                )
                            else:
                                kw_guidance_lines.append(
                                    f"- '{kw}': Integrate into the professional summary or a project/internship bullet "
                                    f"where it fits naturally. DO NOT add to the skills section."
                                )

                        feedback_instruction += (
                            "\n\n📍 KEYWORD PLACEMENT GUIDANCE — these keywords must appear in "
                            "bullets or the professional summary ONLY, never in skills_selected:\n"
                            + "\n".join(kw_guidance_lines)
                        )
                         
        except Exception as exc:
            logger.exception("Error parsing/validating on attempt %d: %s", attempt + 1, exc)
            feedback_instruction = f"Failed to parse or validate JSON response. Ensure the output is valid JSON according to the schema: {exc}"
            last_errors = [str(exc)]
            if attempt >= 1:
                # Syntax errors/exceptions also don't get the extra buzzword budget
                break

    # If the summary STILL contains buzzwords and all errors are exclusively buzzword errors, apply python fallback
    if last_errors and parsed_data and isinstance(parsed_data.get("tailored_resume"), dict):
        is_buzzword_only = all("banned buzzword phrase" in err for err in last_errors)
        if is_buzzword_only:
            original_summary = parsed_data["tailored_resume"].get("summary", "")
            cleaned_summary = deterministic_buzzword_cleanup(original_summary)
            logger.warning("LAST-RESORT FALLBACK: LLM failed to self-correct buzzwords after 4 attempts. Summary cleaned: '%s' -> '%s'", original_summary, cleaned_summary)
            parsed_data["tailored_resume"]["summary"] = cleaned_summary
            
            # Re-run validation one last time
            errors, unverified_items = validate_tailored_resume(parsed_data, master_resume, selected_keywords, return_unverified=True)
            if not errors:
                logger.info("Tailored resume passed validation after applying last-resort cleanup fallback.")
                if "tailored_resume" in parsed_data and "skills_selected" in parsed_data["tailored_resume"]:
                    parsed_data["tailored_resume"]["skills_selected"] = deduplicate_skills_selected(
                        parsed_data["tailored_resume"]["skills_selected"]
                    )
                parsed_data["unverified_skills"] = unverified_items
                return parsed_data
            else:
                last_errors = errors

    # FINAL FALLBACK: if we have a parsed resume with only missing-keyword issues
    # (no schema/structural errors), use the best attempt instead of failing the whole request.
    if parsed_data and isinstance(parsed_data.get("tailored_resume"), dict):
        only_missing_keywords = all(
            "Missing user-selected keywords" in err or "banned buzzword phrase" in err
            for err in last_errors
        )
        if only_missing_keywords:
            # Apply deterministic buzzword cleanup before returning — catches any
            # remaining buzzwords (e.g. 'proven ability') that survived all retry attempts.
            if isinstance(parsed_data.get("tailored_resume"), dict):
                original_summary = parsed_data["tailored_resume"].get("summary", "")
                cleaned_summary = deterministic_buzzword_cleanup(original_summary)
                if cleaned_summary != original_summary:
                    logger.warning(
                        "FINAL FALLBACK: Applied deterministic buzzword cleanup to summary before returning."
                    )
                parsed_data["tailored_resume"]["summary"] = cleaned_summary

            logger.warning(
                "FINAL FALLBACK: Using best available attempt despite unresolved validation issues: %s",
                last_errors
            )
            if "tailored_resume" in parsed_data and "skills_selected" in parsed_data["tailored_resume"]:
                parsed_data["tailored_resume"]["skills_selected"] = deduplicate_skills_selected(
                    parsed_data["tailored_resume"]["skills_selected"]
                )
            parsed_data["unverified_skills"] = []
            return parsed_data

    raise ValueError(f"Resume validation failed after attempts: {', '.join(last_errors)}")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def generate_content_with_fallback(
    client: Any,
    prompt: str,
    system_instruction: str,
    temperature: float,
) -> Any:
    """
    Tries to generate content using GEMINI_MODELS list sequentially.
    On 429/503, performs exponential backoff retries.
    On 404 (model not found), falls back immediately.
    On any other error, falls back to the next model.
    """
    from google.genai import types as genai_types
    from google.genai.errors import APIError

    last_exception = None

    for model in GEMINI_MODELS:
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                logger.info("Attempting generation using model: %s (attempt %d/%d)...", model, attempt + 1, max_retries + 1)
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=temperature,
                    ),
                )
                logger.info("Generation successful using model: %s", model)
                return response
            except APIError as exc:
                last_exception = exc
                err_msg = str(exc).lower()
                status_code = getattr(exc, "code", None)

                # Check if it's 404 (Model not found)
                if status_code == 404 or "404" in err_msg or "not_found" in err_msg:
                    logger.warning("Model %s not found (404). Falling back immediately...", model)
                    break  # Break out of attempts loop to try the next model

                # Check if it's a transient error (429 or 503)
                is_transient = (status_code in (429, 503) or
                                any(term in err_msg for term in ["429", "503", "resource_exhausted", "quota", "unavailable"]))

                if is_transient and attempt < max_retries:
                    # Exponential backoff: 2s, 4s
                    delay = (2 ** attempt) * 2 + random.uniform(0.1, 0.5)
                    logger.warning("Transient error (%s) on model %s. Retrying in %.2fs...", status_code or "APIError", model, delay)
                    time.sleep(delay)
                    continue
                else:
                    logger.warning("Model %s failed with error: %s. Falling back to next model...", model, exc)
                    break
            except Exception as exc:
                last_exception = exc
                logger.warning("Unexpected error on model %s: %s. Falling back to next model...", model, exc)
                break

    if last_exception:
        raise last_exception
    raise RuntimeError("All models failed to generate content.")


def extract_master_entities(master_resume: str) -> dict[str, Any]:
    """
    Extracts all unique factual entities grouped by sections (and skills, contact) from the raw master resume.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {}

    from google import genai
    from google.genai import types as genai_types
    client = genai.Client(api_key=api_key)

    system_instruction = """You are an expert resume parser. Your job is to extract every unique factual entity and detail from the candidate's resume raw text.
Do NOT assume any specific resume structure. Dynamically detect all sections present in the resume text.

For each section (such as Work Experience, Internships, Projects, Education, Certifications, Awards, Languages, Volunteer Work, Research, Publications, Achievements, etc.), extract all unique factual entities (e.g. company names, job titles, project names, degree names, university names, certification names, languages spoken, specific awards).

Also extract all technical skills/technologies and contact details (email, phone, links/URLs).

Return ONLY a valid JSON object matching this schema:
{
  "sections": [
    {
      "name": "<section name, e.g. Education, Projects, Experience>",
      "entities": ["<entity 1, e.g. University of California, Berkeley>", "<entity 2, e.g. Bachelor of Science in Computer Science>"]
    }
  ],
  "skills": ["<skill 1>", "<skill 2>"],
  "contact": ["<contact item 1, e.g. alex.jordan@email.com>", "<contact item 2, e.g. https://github.com/alexjordan>"]
}"""

    prompt = f"Parse the following resume text and extract all unique factual entities section-by-section:\n\n{master_resume}"
    try:
        response = generate_content_with_fallback(
            client=client,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.1
        )
        cleaned = _strip_markdown_fences(response.text)
        return json.loads(cleaned)
    except Exception as exc:
        logger.error("Failed to extract master entities: %s", exc)
        return {
            "sections": [],
            "skills": [],
            "contact": []
        }


def check_completeness(master_entities: dict[str, Any], tailored: dict[str, Any]) -> list[str]:
    """
    Compares master resume entities with the tailored resume dictionary.
    Returns a list of error strings representing missing factual details.
    """
    errors = []
    if not master_entities or not tailored:
        return errors

    # Helper to check if a string is present in a target (case-insensitive, handles normalization/acronyms/substrings)
    def is_present(value: str, target: Any) -> bool:
        if not value:
            return True
        val_lower = value.strip().lower()
        if not val_lower:
            return True

        # Custom normalization rules for common variants
        def clean_val(v: str) -> str:
            v = v.lower()
            v = re.sub(r"[\s\-]+", "", v)
            v = v.replace("apis", "api").replace("libraries", "library").replace("frameworks", "framework")
            return v

        val_norm = clean_val(val_lower)

        def _search(obj: Any) -> bool:
            if isinstance(obj, str):
                obj_lower = obj.lower()
                if val_lower in obj_lower:
                    return True
                obj_norm = clean_val(obj_lower)
                if val_norm in obj_norm or obj_norm in val_norm:
                    return True
                return False
            elif isinstance(obj, dict):
                return any(_search(v) for v in obj.values())
            elif isinstance(obj, list):
                return any(_search(item) for item in obj)
            return False

        return _search(target)

    # 1. Validate generic sections and their entities
    for sec in master_entities.get("sections", []):
        sec_name = sec.get("name", "")
        entities = sec.get("entities", [])
        for ent in entities:
            # We want to check if this entity is present anywhere in the tailored resume
            if not is_present(ent, tailored):
                # Try partial matching for compound strings (ignoring common role keywords)
                tokens = [t for t in re.split(r"[\s,;/()\-]+", ent.lower()) if len(t) > 3 and t not in ["bachelor", "master", "science", "degree", "associate", "secondary", "higher", "technology", "engineering", "intern", "developer"]]
                if tokens:
                    found = False
                    for t in tokens:
                        if is_present(t, tailored):
                            found = True
                            break
                    if not found:
                        errors.append(f"Missing factual entity '{ent}' from section '{sec_name}'.")
                else:
                    errors.append(f"Missing factual entity '{ent}' from section '{sec_name}'.")

    # 2. Check Technical Skills
    for skill in master_entities.get("skills", []):
        skill_clean = skill.strip().lower()
        if len(skill_clean) < 3 or skill_clean in ["and", "with", "using", "for"]:
            continue
        
        found = is_present(skill_clean, tailored)
        if not found:
            tokens = [t for t in re.split(r"[\s,;/()\-]+", skill_clean) if len(t) > 2]
            if tokens:
                for t in tokens:
                    if is_present(t, tailored):
                        found = True
                        break
        if not found:
            errors.append(f"Missing technical skill '{skill}'.")

    # 3. Check Contact Info & Links
    for link in master_entities.get("contact", []):
        if len(link.strip()) > 3:
            if not is_present(link, tailored):
                errors.append(f"Missing contact info or link '{link}'.")

    return errors


def clean_tailored_resume(data: dict[str, Any], master_resume: str) -> dict[str, Any]:
    """
    Applies strict Python-based cleaning guardrails to ensure LLM output does not:
    1. Open with banned buzzwords (like 'Forward-thinking').
    2. Invent coursework if not in master resume.
    3. Include unearned stakeholder/deployment claims.
    4. Include inflated enterprise project descriptions.
    5. Leave broken/mangled phrases from LLM generation artifacts.
    """
    if not isinstance(data, dict):
        return data
    # 0. Normalize contact URLs — strip https:// and http:// prefixes for clean display
    contact = data.get("contact", {})
    if isinstance(contact, dict):
        for url_field in ("linkedin", "github", "portfolio", "website"):
            val = contact.get(url_field, "")
            if isinstance(val, str) and val.strip():
                contact[url_field] = re.sub(r'^https?://', '', val.strip())

    # 1. Clean Summary: Strip any banned buzzwords (case-insensitive)
    # Buzzwords banned only as the sentence/summary opener — NOT stripped mid-sentence.
    OPENER_ONLY_BUZZWORDS = {"experienced"}

    # Buzzwords banned anywhere in the summary opener loop.
    OPENER_BANNED_BUZZWORDS = [
        "forward-thinking", "forward thinking", "dynamic", "passionate",
        "results-driven", "results driven", "motivated", "dedicated",
        "energetic", "creative", "innovative", "proven ability",
        "successful", "highly skilled", "detail-oriented", "detail oriented",
        "enthusiastic", "proactive"
    ]

    summary = data.get("summary", "").strip()
    if summary:
        # Strip opener-only buzzwords from the very start of the summary only.
        # "experienced" is in this bucket — it's fine mid-sentence
        # ("hands-on experience in X") but wrong as an opener.
        while True:
            stripped_check = re.sub(r'^(a|an|the)\s+', '', summary, flags=re.IGNORECASE).strip()
            opener_match = None
            for buzz in OPENER_ONLY_BUZZWORDS:
                m = re.match(
                    r'^' + re.escape(buzz) + r'(?:\b|,|\s*and\s*|\s*with\s*)*',
                    stripped_check,
                    re.IGNORECASE
                )
                if m:
                    opener_match = m
                    # Recompute offset in original summary
                    article_m = re.match(r'^(a|an|the)\s+', summary, re.IGNORECASE)
                    offset = article_m.end() if article_m else 0
                    summary = summary[offset + m.end():].strip()
                    break
            if not opener_match:
                break

        # Strip anywhere-banned buzzwords from the opener (original behaviour).
        while True:
            pattern = (
                r"^(?:a|an|the)?\s*("
                + "|".join(re.escape(b) for b in OPENER_BANNED_BUZZWORDS)
                + r")(?:\b|,|\s*and\s*|\s*with\s*)*"
            )
            match = re.match(pattern, summary, re.IGNORECASE)
            if not match:
                break
            summary = summary[match.end():].strip()

        if not summary:
            summary = "Software engineer focused on full-stack application development."

        summary = summary[0].upper() + summary[1:]
        data["summary"] = summary

    # 2. Clean Coursework: Ensure no coursework is generated if not in master resume
    master_lower = master_resume.lower()
    has_coursework_in_master = "coursework" in master_lower or "subjects" in master_lower or "relevant course" in master_lower
    if not has_coursework_in_master:
        for edu in data.get("education", []):
            edu["relevant_coursework"] = ""

    # 3. Clean Project & Experience inflation, unearned claims, and LLM generation artifacts
    inflated_phrases = {
        "proven ability to deploy, customize, and troubleshoot scalable systems": "experienced in building, testing, and debugging full-stack web applications",
        "proven ability to deploy, customize, and troubleshoot": "experienced in building, testing, and debugging",
        "collaborating closely with stakeholders to drive product adoption": "implementing clean, functional UI/UX and efficient backend APIs",
        "collaborating closely with stakeholders": "collaborating with team members",
        "drive product adoption": "ensure correct implementation",
        "mirror enterprise-level sap/erp functionality": "implement ERP-inspired user flows and business process automation",
        "mirror enterprise-level sap/erp": "implement ERP-inspired",
        "enterprise-level sap/erp": "ERP-inspired",
        "enterprise-level": "project-level",
        "enterprise grade": "project grade",
        "enterprise-grade": "functional",
        "production-grade": "well-tested",
        "production grade": "well-tested",
        "industry-standard": "reliable",
        "industry standard": "reliable",
    }

    # Regex-based artifact fixes — catches LLM-mangled phrases that simple
    # string replacement can't reliably target (e.g. "applying reliables",
    # "applying reliable practices", "applying reliable patterns", etc.)
    ARTIFACT_REGEX_FIXES = [
        # "applying reliable(s/patterns/practices/...) in X architecture"
        # → "following best practices in X architecture"
        (
            r'\bapplying\s+reliables?\s+(?:practices?\s+|patterns?\s+|principles?\s+)?in\b',
            'following best practices in'
        ),
        # Catch bare "applying reliables" without trailing "in"
        (
            r'\bapplying\s+reliables\b',
            'applying reliable practices'
        ),
    ]

    def sanitize_text(text: str) -> str:
        if not isinstance(text, str):
            return text
        lower_text = text.lower()
        # 1. String-match inflated phrases (case-insensitive)
        for phrase, replacement in inflated_phrases.items():
            if phrase in lower_text:
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                text = pattern.sub(replacement, text)
                lower_text = text.lower()
        # 2. Regex-based artifact fixes
        for pattern, replacement in ARTIFACT_REGEX_FIXES:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    # Clean summary, project bullets, internship bullets
    if "summary" in data:
        data["summary"] = sanitize_text(data["summary"])

    for proj in data.get("flagship_projects_selected", []):
        if "bullets" in proj and isinstance(proj["bullets"], list):
            proj["bullets"] = [sanitize_text(bullet) for bullet in proj["bullets"]]

    for proj in data.get("other_projects_selected", []):
        if "bullets" in proj and isinstance(proj["bullets"], list):
            proj["bullets"] = [sanitize_text(bullet) for bullet in proj["bullets"]]

    for intern in data.get("internships_selected", []):
        if "bullets" in intern and isinstance(intern["bullets"], list):
            intern["bullets"] = [sanitize_text(bullet) for bullet in intern["bullets"]]

    # Also clean projects list (populated after repair, used by pdf_service)
    for proj in data.get("projects", []):
        if "bullets" in proj and isinstance(proj["bullets"], list):
            proj["bullets"] = [sanitize_text(bullet) for bullet in proj["bullets"]]

    return data

    def sanitize_text(text: str) -> str:
        if not isinstance(text, str):
            return text
        lower_text = text.lower()
        for phrase, replacement in inflated_phrases.items():
            if phrase in lower_text:
                # Use case-insensitive replacement
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                text = pattern.sub(replacement, text)
        return text

    # Clean summary, project bullets, internship bullets
    if "summary" in data:
        data["summary"] = sanitize_text(data["summary"])

    for proj in data.get("flagship_projects_selected", []):
        if "bullets" in proj and isinstance(proj["bullets"], list):
            proj["bullets"] = [sanitize_text(bullet) for bullet in proj["bullets"]]

    for proj in data.get("other_projects_selected", []):
        if "bullets" in proj and isinstance(proj["bullets"], list):
            proj["bullets"] = [sanitize_text(bullet) for bullet in proj["bullets"]]

    for intern in data.get("internships_selected", []):
        if "bullets" in intern and isinstance(intern["bullets"], list):
            intern["bullets"] = [sanitize_text(bullet) for bullet in intern["bullets"]]

    return data


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json … ``` or ``` … ``` wrappers if Gemini added them."""
    pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_json_response(raw: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Strip fences, parse JSON, and do a basic schema sanity-check."""
    cleaned = _strip_markdown_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Gemini returned non-JSON: %s", cleaned[:500])
        raise ValueError(
            f"Gemini response could not be parsed as JSON: {exc}"
        ) from exc

    required_keys = {
        "contact",
        "summary",
        "skills_selected",
        "flagship_projects_selected",
        "other_projects_selected",
        "internships_selected",
        "education",
        "certifications",
    }

    if "tailored_resume" in data:
        resume_data = data["tailored_resume"]
        dashboard_data = data.get("dashboard")
    else:
        resume_data = data
        dashboard_data = None

    missing = required_keys - set(resume_data.keys())
    if missing:
        raise ValueError(
            f"Gemini response is missing required keys: {missing}"
        )

    return resume_data, dashboard_data


def analyze_jd_match(master_resume: str, jd_text: str) -> dict[str, Any]:
    """
    Analyzes the master resume against the job description and returns match statistics.
    Returns:
        A dict matching the schema:
        {
            "overall_match_percentage": int,
            "matched_requirements": list[str],
            "missing_requirements": list[str],
            "experience_level_fit": str
        }
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    analysis_system_instruction = """You are a job applicant screening expert. Your job is to \
honestly and objectively evaluate a candidate's master resume against a job description (JD). \
Your evaluation must be 100% honest and accurate, pointing out both matches and gaps. \
Do not exaggerate, stretch, or assume skills that are not explicitly present. \
Return ONLY valid JSON matching this exact schema — no markdown, no prose, no code fences:
{
  "overall_match_percentage": <integer between 0 and 100>,
  "matched_requirements": ["<string>"],
  "missing_requirements": ["<string>"],
  "experience_level_fit": "<string>",
  "master_keywords": ["<string>"],
  "jd_keywords": ["<string>"],
  "keyword_alignments": [
    {
      "keyword": "<string>",
      "status": "<'integrated' or 'gap'>",
      "detail": "<string explaining how it is matched/reworded in the resume, or why it is a gap>"
    }
  ]
}"""

    prompt = f"""Evaluate the candidate's resume against the Job Description.

Master Resume Content:
{master_resume}

---

Job Description:
{jd_text}

---

Please perform the evaluation and return the JSON according to the schema.
For 'matched_requirements', list specific requirements from the JD that are satisfied, with a brief mention of which project, internship, or education entry in the resume supports it.
For 'missing_requirements', list specific requirements (tech stack, languages, tools, databases, or processes) from the JD that are not mentioned anywhere in the resume.
For 'experience_level_fit', write a short honest assessment of the fit between the JD's required years of experience and the candidate's actual timeline.
For 'master_keywords', extract a list of all key technologies, tools, skills, and languages mentioned in the candidate's master resume.
For 'jd_keywords', extract a list of all key technologies, tools, skills, and languages mentioned in the Job Description.
For 'keyword_alignments', extract a list of all key technologies, tools, skills, and languages mentioned in the JD. For each keyword:
  - If the candidate possesses a corresponding skill or experience (even if named slightly differently in the master resume), mark status as 'integrated' and provide a detail showing how it aligns (e.g. "REST APIs - reworded from REST-based backend modules").
  - If the candidate does not possess that skill, mark status as 'gap' and write "Not present in master resume".
"""

    try:
        response = generate_content_with_fallback(
            client=client,
            prompt=prompt,
            system_instruction=analysis_system_instruction,
            temperature=0.1
        )
    except Exception as exc:
        logger.error("All models failed during match analysis: %s", exc)
        raise

    raw_text: str = response.text
    logger.info("Received match analysis response (%d chars).", len(raw_text))

    cleaned = _strip_markdown_fences(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Gemini returned non-JSON for match analysis: %s", cleaned[:500])
        raise ValueError(
            f"Gemini response could not be parsed as JSON: {exc}"
        ) from exc

    required_keys = {
        "overall_match_percentage",
        "matched_requirements",
        "missing_requirements",
        "experience_level_fit",
        "master_keywords",
        "jd_keywords",
        "keyword_alignments",
    }
    missing = required_keys - set(data.keys())
    if missing:
        raise ValueError(
            f"Gemini match analysis response is missing required keys: {missing}"
        )

    return data


# ---------------------------------------------------------------------------
# Quality Gate Validation & Self-Correction
# ---------------------------------------------------------------------------

BANNED_BUZZWORDS = [
    "forward-thinking", "forward thinking", "dynamic", "passionate", 
    "results-driven", "results driven", "motivated", "dedicated", 
    "energetic", "creative", "experienced", "innovative", "proven ability", 
    "proven track record", "proven track record of",
    "successful", "highly skilled", "detail-oriented", "detail oriented", 
    "enthusiastic", "proactive"
]

WEAK_OPENERS = [
    "worked on", "helped with", "responsible for", "assisted in", 
    "involved in", "participated in", "handled", "did", "assisted with",
    "helped to", "responsible to", "worked with"
]

VAGUE_ENDINGS = [
    "to meet requirements", "to ensure compliance", "mirroring project-level reporting requirements",
    "to achieve goals", "to complete the task", "for testing purposes", "to ensure functionality",
    "in a timely manner", "to deliver results", "with industry-standard tools", "to satisfy stakeholders",
    "mirroring project-level reporting", "meeting project requirements", "ensuring functionality"
]

def check_summary_text(summary: str) -> list[str]:
    """Check summary for banned buzzwords and other quality issues."""
    errors = []
    summary_lower = summary.strip().lower()

    # Words that are only banned as openers (first word or first few words),
    # not when used naturally mid-sentence.
    OPENER_ONLY_BUZZWORDS = {"experienced"}

    # Words that are banned anywhere in the summary.
    ANYWHERE_BUZZWORDS = [
        bw for bw in BANNED_BUZZWORDS if bw not in OPENER_ONLY_BUZZWORDS
    ]

    # Check anywhere-banned buzzwords across the full summary text.
    for buzz in ANYWHERE_BUZZWORDS:
        if buzz in summary_lower:
            errors.append(f"Summary text contains the banned buzzword phrase '{buzz}'.")

    # Check opener-only buzzwords — only flag if the summary starts with them.
    # Strips leading articles (a/an/the) before checking.
    stripped_opener = re.sub(r'^(a|an|the)\s+', '', summary_lower).strip()
    for buzz in OPENER_ONLY_BUZZWORDS:
        if stripped_opener.startswith(buzz):
            errors.append(
                f"Summary text opens with the banned buzzword phrase '{buzz}'. "
                f"Do not start the summary with '{buzz}' — open directly with the candidate's identity or expertise."
            )

    return errors


def check_bullet_text(bullet: str) -> list[str]:
    """Check a bullet point for weak verbs, vague endings, and length."""
    errors = []
    bullet_stripped = bullet.strip()
    bullet_lower = bullet_stripped.lower()
    
    # 1. Weak openers
    for opener in WEAK_OPENERS:
        if bullet_lower.startswith(opener) or bullet_lower.startswith("was " + opener):
            errors.append(f"Bullet starts with weak opener: '{opener}'")
            
    # 2. Vague endings
    for ending in VAGUE_ENDINGS:
        cleaned_bullet = bullet_lower.rstrip(".! ")
        if cleaned_bullet.endswith(ending):
            errors.append(f"Bullet ends with vague/generic filler: '{ending}'")
            
    # 3. Length check
    if len(bullet_stripped) > 250:
        errors.append("Bullet is too long (greater than 250 characters)")
        
    return errors


def check_repeated_starting_verbs(bullets: list[str]) -> list[str]:
    """Checks if multiple bullets in a section start with the same verb (verb duplication)."""
    errors = []
    verbs = []
    for b in bullets:
        words = b.strip().split()
        if words:
            # Clean punctuation from the verb
            verb = re.sub(r"[^\w]", "", words[0]).lower()
            if len(verb) > 2:
                verbs.append(verb)
    
    duplicates = [v for v, count in collections.Counter(verbs).items() if count > 1]
    if duplicates:
        errors.append(f"Start verb duplication detected: multiple bullets start with the same verb(s): {', '.join(duplicates)}. Ensure verb rotation.")
    return errors


PASSIVE_VOICE_TRIGGERS = [
    "was designed", "were designed", "was built", "were built", 
    "was developed", "were developed", "was implemented", "were implemented",
    "was created", "were created", "was optimized", "were optimized",
    "was tested", "were tested", "was run", "were run", "was responsible for",
    "were responsible for", "was involved in", "were involved in"
]

def check_passive_voice(bullet: str) -> list[str]:
    """Checks if a bullet is written in passive voice instead of active voice."""
    errors = []
    bullet_lower = bullet.lower()
    for trigger in PASSIVE_VOICE_TRIGGERS:
        if trigger in bullet_lower:
            errors.append(f"Passive voice trigger '{trigger}' detected. Rephrase to active voice starting with a strong action verb.")
    return errors


def check_repeated_bullets(bullets: list[str]) -> list[str]:
    """Checks if there are duplicate or near-duplicate bullets in a section."""
    errors = []
    seen = set()
    for b in bullets:
        b_norm = re.sub(r"\s+", "", b.lower())
        if b_norm in seen:
            errors.append(f"Duplicate bullet point detected: '{b[:40]}...'")
        seen.add(b_norm)
    return errors


def check_keyword_stuffing(bullet: str) -> list[str]:
    """Checks if a single technical term is repeated excessively in a single bullet point."""
    errors = []
    words = [w.strip(".,;:()[]\"'").lower() for w in bullet.split()]
    counts = collections.Counter(words)
    for word, count in counts.items():
        if len(word) >= 4 and count > 2:
            errors.append(f"Keyword stuffing detected: term '{word}' is repeated {count} times in a single bullet.")
    return errors


GENERIC_JD_PHRASES = [
    "software applications", "internet-related tools", "software systems design",
    "internet-related systems", "related tools", "software systems"
]

def check_generic_jd_phrases(bullet: str) -> list[str]:
    """Checks if generic job description phrases were copied verbatim without mapping to specific candidate experience."""
    errors = []
    bullet_lower = bullet.lower()
    for phrase in GENERIC_JD_PHRASES:
        if phrase in bullet_lower:
            errors.append(f"Generic JD phrase '{phrase}' copied without candidate context. Map to specific terms (e.g. REST APIs, web apps).")
    return errors


def clean_master_project_line(line: str) -> str:
    # Strip leading bullets or numbering
    line = re.sub(r'^\s*[\d\.\-\*•]+\s*', '', line).strip()
    
    # Regex for date range
    date_pattern = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}\s*(?:[-–—]|to)\s*(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4})\b'
    
    # Remove date range (with or without surrounding parentheses/brackets)
    line = re.sub(rf'\(\s*{date_pattern}\s*\)', '', line, flags=re.IGNORECASE)
    line = re.sub(rf'\[\s*{date_pattern}\s*\]', '', line, flags=re.IGNORECASE)
    line = re.sub(date_pattern, '', line, flags=re.IGNORECASE).strip()
    
    # Strip any trailing delimiters (like dashes or commas) left over after date removal
    line = re.sub(r'\s*[-–—,]+\s*$', '', line).strip()
    return line


def find_full_project_title_from_blob(ai_name: str, master_resume: str) -> str | None:
    ai_name_lower = ai_name.lower().strip()
    core_name = re.split(r'[\u2013-]', ai_name_lower)[0].strip()
    if not core_name or len(core_name) < 4:
        return None
        
    master_lower = master_resume.lower()
    start_idx = master_lower.find(core_name)
    if start_idx == -1:
        words = [w for w in re.split(r'[^\w\d]+', core_name) if w]
        if words and len(words[0]) >= 4:
            start_idx = master_lower.find(words[0])
            
    if start_idx == -1:
        return None
        
    # Search forward up to 250 characters for a date range
    search_sub = master_resume[start_idx:start_idx + 250]
    date_pattern = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}\s*(?:[-–—]|to)\s*(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4})\b'
    
    match = re.search(date_pattern, search_sub, flags=re.IGNORECASE)
    if match:
        title_part = search_sub[:match.start()]
    else:
        title_part = search_sub.splitlines()[0]
        
    title_part = re.sub(r'^\s*[\d\.\-\*•]+\s*', '', title_part).strip()
    title_part = re.sub(r'\s+', ' ', title_part).strip()
    title_part = re.sub(r'\s*[-–—,]+\s*$', '', title_part).strip()
    return title_part


def restore_full_project_names(tailored_data: dict[str, Any], master_resume: str):
    resume = tailored_data.get("tailored_resume", {})
    projects = resume.get("projects", [])
    if not projects:
        return
        
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        ai_name = proj.get("name", "").strip()
        if not ai_name:
            continue
            
        full_title = find_full_project_title_from_blob(ai_name, master_resume)
        if full_title and ai_name != full_title:
            logger.info("Restoring project title: '%s' -> '%s'", ai_name, full_title)
            proj["name"] = full_title


def restore_project_links(tailored_data: dict[str, Any], master_resume: str):
    resume = tailored_data.get("tailored_resume", {})
    projects = resume.get("projects", [])
    if not projects:
        return
        
    master_lines = [line.strip() for line in master_resume.splitlines() if line.strip()]
    
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        name = proj.get("name", "")
        if not name:
            continue
            
        name_lower = name.lower()
        name_clean = re.split(r"[\u2013-]", name_lower)[0].strip() # split by dash/en-dash
        
        proj_idx = -1
        for i, line in enumerate(master_lines):
            if name_clean in line.lower():
                proj_idx = i
                break
                
        if proj_idx != -1:
            known_headers = {
                "summary", "professional summary", "skills", "technical skills", 
                "projects", "personal projects", "academic projects", 
                "work experience", "experience", "employment", "professional experience",
                "internships", "internship experience", "education", "certifications", "publications"
            }
            
            master_links = []
            for j in range(proj_idx, min(proj_idx + 8, len(master_lines))):
                line_j = master_lines[j]
                if j > proj_idx and line_j.lower().rstrip(":") in known_headers:
                    break
                
                words = re.split(r'[\s|]+', line_j)
                for w in words:
                    w_clean = w.strip("(),;[]*•|")
                    w_lower = w_clean.lower()
                    if ("github.com" in w_lower or 
                        "onrender.com" in w_lower or 
                        "vercel.app" in w_lower or 
                        "github.io" in w_lower or 
                        w_lower.startswith("http://") or 
                        w_lower.startswith("https://")):
                        master_links.append(w_clean)
            
            if not master_links:
                continue
                
            tailored_links = []
            for k in ["github_link", "live_demo", "project_url", "website"]:
                val = proj.get(k)
                if val:
                    tailored_links.append(val.strip().lower())
            for link_item in proj.get("links", []):
                if isinstance(link_item, str):
                    tailored_links.append(link_item.strip().lower())
                elif isinstance(link_item, dict) and link_item.get("url"):
                    tailored_links.append(link_item["url"].strip().lower())
                    
            for m_link in master_links:
                m_link_lower = m_link.lower()
                is_present = False
                for t_link in tailored_links:
                    if m_link_lower in t_link or t_link in m_link_lower:
                        is_present = True
                        break
                if not is_present:
                    if "github.com" in m_link_lower:
                        if not proj.get("github_link"):
                            proj["github_link"] = m_link
                            logger.info(f"Restored missing github_link for project '{name}': {m_link}")
                    else:
                        if not proj.get("live_demo"):
                            proj["live_demo"] = m_link
                            logger.info(f"Restored missing live_demo for project '{name}': {m_link}")
                        elif not proj.get("project_url"):
                            proj["project_url"] = m_link
                            logger.info(f"Restored missing project_url for project '{name}': {m_link}")


def validate_tailored_resume(tailored_data: dict[str, Any], master_resume: str, selected_keywords: list[str] | None = None, return_unverified: bool = False) -> list[str] | tuple[list[str], list[dict[str, str]]]:
    """
    Lightweight validation check:
    a) Schema verification for required top-level keys
    b) Check that tailored counts match ground truth entry_counts (projects, internships, education)
    c) Buzzword checks in summary text
    d) Skills section floor check (at least 5 total items)
    e) Certifications & publications count checks against computed ground truth
    f) Project links preservation check
    g) Fabrication check: skills & project technologies must be present in raw master resume text
    h) Keyword integration check: verify all user-selected keywords are integrated
    """
    # Restore/Correct project titles and links automatically
    restore_full_project_names(tailored_data, master_resume)
    restore_project_links(tailored_data, master_resume)
    
   # Define approx entry counter (rewritten: count date-range occurrences,
    # since every entry in projects/internships/education has exactly one
    # date range — this is far more reliable than counting non-empty lines,
    # which was drastically overcounting by treating tech-stack lines,
    # bullet lines, and any line >5 chars as a "new entry".
    DATE_RANGE_PATTERN = (
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4}'
        r'\s*(?:[-–—]|to)\s*'
        r'(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4})'
    )

    KNOWN_SECTION_HEADERS = [
        "professional summary", "summary", "technical skills", "skills",
        "projects", "flagship projects", "other projects", "personal projects",
        "internship experience", "internships", "work experience", "experience",
        "employment", "professional experience", "education", "certifications",
        "publications"
    ]

    def count_approx_entries(section_keyword: str) -> int:
        lines = master_resume.splitlines()
        found_section = False
        section_lines = []
        for line in lines:
            line_strip = line.strip()
            if not line_strip:
                continue
            line_lower = line_strip.lower()

            if not found_section:
                if (
                    line_lower == section_keyword
                    or line_lower.rstrip(":") == section_keyword
                    or (line_strip.isupper() and section_keyword in line_lower)
                ):
                    found_section = True
                continue

            # Stop if we hit another known section header
            is_header = False
            for header in KNOWN_SECTION_HEADERS:
                if line_lower == header or line_lower.rstrip(":") == header:
                    if header != section_keyword:
                        is_header = True
                        break
            if is_header:
                break
            # Also stop on ALL CAPS lines that look like a different section header
            if line_strip.isupper() and any(
                h in line_lower for h in
                ["education", "experience", "projects", "skills",
                 "publications", "certifications", "internship"]
            ) and section_keyword not in line_lower:
                break

            section_lines.append(line_strip)
        print(f"{section_keyword}: {len(section_lines)} lines")
        section_text = "\n".join(section_lines)

        save_json(
            f"debug_section_{section_keyword}.json",
            {
                "section": section_keyword,
                "lines": section_lines,
                "text": section_text,
            },
        )

        # Primary method: count date-range occurrences (1 entry = 1 date range)
        date_matches = re.findall(DATE_RANGE_PATTERN, section_text, flags=re.IGNORECASE)
        if date_matches:
            return len(date_matches)

        # Fallback (used only for sections without dates, e.g. certifications
        # that may list just name/issuer, or publications without a range):
        # count bulleted lines, or non-empty lines if no bullets are present.
        bullet_lines = [
            l for l in section_lines
            if l.startswith(("-", "*", "•"))
        ]
        if bullet_lines:
            return len(bullet_lines)

        non_empty_lines = [l for l in section_lines if l]
        return len(non_empty_lines)

    # Inject/supplement entry_counts dynamically if missing or incomplete
    # Always compute entry_counts ourselves from the raw master resume text.
    # Never trust any self-reported entry_counts the LLM may have invented,
    # since there is no schema definition forcing it to be accurate.
    tailored_data["entry_counts"] = {}
    counts = tailored_data["entry_counts"]
    counts["master_projects_count"] = count_approx_entries("projects")
    count_intern = count_approx_entries("internship")
    count_exp = count_approx_entries("experience")
    count_emp = count_approx_entries("employment")
    counts["master_internships_count"] = max(count_intern, count_exp, count_emp)
    counts["master_education_count"] = count_approx_entries("education")
    
    errors = []
    unverified_items = []

    # a) required top-level keys
    required_keys = {"tailored_resume", "entry_counts", "dashboard"}
    missing_keys = required_keys - set(tailored_data.keys())
    if missing_keys:
        errors.append(f"Missing required top-level keys: {', '.join(missing_keys)}")
        logger.warning("Validation (Schema check): FAIL. Missing keys: %s", missing_keys)
        if return_unverified:
            return errors, unverified_items
        return errors
    logger.info("Validation (Schema check): PASS")

    resume = tailored_data["tailored_resume"]
    counts = tailored_data["entry_counts"]

    # Check inner keys
    sub_keys = {"summary", "skills_selected", "projects", "internships_selected", "education", "certifications", "section_order", "section_titles"}
    missing_sub = sub_keys - set(resume.keys())
    if missing_sub:
        errors.append(f"Missing required keys in tailored_resume: {', '.join(missing_sub)}")
        logger.warning("Validation (Sub-keys check): FAIL. Missing sub-keys: %s", missing_sub)
        if return_unverified:
            return errors, unverified_items
        return errors
    logger.info("Validation (Sub-keys check): PASS")

    # b) Entry count check for projects, internships_selected, education
    sections_to_check = [
        ("projects", "master_projects_count"),
        ("internships_selected", "master_internships_count"),
        ("education", "master_education_count"),
    ]
    for section_field, count_field in sections_to_check:
        expected = counts.get(count_field, 0)
        actual = len(resume.get(section_field, []))
        if actual < expected:
            errors.append(f"Entry count mismatch for section '{section_field}': tailored count ({actual}) is less than master count ({expected})")

    # c) Buzzword checks in summary text
    summary = resume.get("summary", "")
    summary_errors = check_summary_text(summary)
    if summary_errors:
        errors.extend(summary_errors)

    # d) Skills section floor check (at least 5 total items)
    total_skills = 0
    for group in resume.get("skills_selected", []):
        if isinstance(group, dict):
            total_skills += len(group.get("items", []))
    if total_skills < 5:
        errors.append(f"Skills section floor check failed: total skill items ({total_skills}) is less than 5.")

    # e) Certifications & publications count checks against computed ground truth
    master_blob = master_resume.lower()
    

    cert_count_master = count_approx_entries("certifications")
    actual_certs = len(resume.get("certifications", []))
    if cert_count_master > 0 and actual_certs < cert_count_master:
        errors.append(f"Certifications section: master resume has approximately {cert_count_master} entries, but tailored has {actual_certs}.")

    pub_count_master = count_approx_entries("publications")
    actual_pubs = len(resume.get("publications", []))
    if pub_count_master > 0 and actual_pubs < pub_count_master:
        errors.append(f"Publications section: master resume has approximately {pub_count_master} entries, but tailored has {actual_pubs}.")

    # f) Project links preservation check
    for proj in resume.get("projects", []):
        if not isinstance(proj, dict):
            continue
        name = proj.get("name", "")
        has_github_in_master = False
        has_http_in_master = False
        proj_idx = -1
        master_lines = [line.strip() for line in master_resume.splitlines() if line.strip()]
        name_clean = re.split(r"[\u2013-]", name.lower())[0].strip()
        for i, line in enumerate(master_lines):
            if name_clean in line.lower():
                proj_idx = i
                break
        if proj_idx != -1:
            known_headers = {
                "summary", "professional summary", "skills", "technical skills", 
                "projects", "personal projects", "academic projects", 
                "work experience", "experience", "employment", "professional experience",
                "internships", "internship experience", "education", "certifications", "publications"
            }
            for j in range(proj_idx, min(proj_idx + 8, len(master_lines))):
                line_j = master_lines[j]
                if j > proj_idx and line_j.lower().rstrip(":") in known_headers:
                    break
                if "github.com" in line_j.lower():
                    has_github_in_master = True
                if any(term in line_j.lower() for term in ["http", "live", "vercel.app", "github.io"]):
                    has_http_in_master = True
                    
        tailored_has_links = False
        if proj.get("github_link") or proj.get("project_url") or proj.get("live_demo") or proj.get("website") or proj.get("links") or proj.get("additional_links"):
            tailored_has_links = True
            
        if (has_github_in_master or has_http_in_master) and not tailored_has_links:
            errors.append(
                f"Project links missing for project '{name}': master resume contains a link for this project, "
                f"but no links were preserved in the tailored output. You must preserve all project links."
            )

    # g) Fabrication check with singular/plural and keyword exemptions
    def get_word_variants(word: str) -> list[str]:
        w = word.strip().lower()
        if not w:
            return []
        variants = [w]
        if w.endswith("s") and len(w) > 1:
            variants.append(w[:-1])
        else:
            variants.append(w + "s")
        return variants

    def match_phrase(p1: str, p2: str) -> bool:
        p1_clean = p1.strip().lower()
        p2_clean = p2.strip().lower()
        if p1_clean == p2_clean:
            return True
        if p2_clean in get_word_variants(p1_clean) or p1_clean in get_word_variants(p2_clean):
            return True
        words1 = [w for w in re.split(r"[^\w\d]+", p1_clean) if len(w) > 2]
        words2 = [w for w in re.split(r"[^\w\d]+", p2_clean) if len(w) > 2]
        if words1 and words2 and len(words1) == len(words2):
            all_words_matched = True
            for w1, w2 in zip(words1, words2):
                if w1 != w2 and w1 not in get_word_variants(w2) and w2 not in get_word_variants(w1):
                    all_words_matched = False
                    break
            if all_words_matched:
                return True
        return False

    def is_exempt(item: str) -> bool:
        if not selected_keywords:
            return False
        for kw in selected_keywords:
            if match_phrase(item, kw):
                return True
        return False

    def check_traceability(item: str) -> bool:
        item_clean = item.strip().lower()
        if not item_clean:
            return True
        if item_clean in master_blob:
            return True

        whole_phrase_variants = get_word_variants(item_clean)
        for variant in whole_phrase_variants:
            if variant in master_blob:
                return True

        words = [w for w in re.split(r"[^\w\d]+", item_clean) if len(w) > 2]
        if words:
            all_words_matched = True
            for word in words:
                word_matched = False
                for variant in get_word_variants(word):
                    if variant in master_blob:
                        word_matched = True
                        break
                if not word_matched:
                    all_words_matched = False
                    break
            if all_words_matched:
                return True
        return False

    for group in resume.get("skills_selected", []):
        if not isinstance(group, dict):
            continue
        category = group.get("category", "")
        for item in group.get("items", []):
            if is_exempt(item):
                continue
            if not check_traceability(item):
                unverified_items.append({
                    "item": item,
                    "location": f"skills category: {category}"
                })

    for proj in resume.get("projects", []):
        if not isinstance(proj, dict):
            continue
        name = proj.get("name", "")
        tech_stack = proj.get("tech_stack", "")
        if tech_stack:
            tech_items = [t.strip() for t in re.split(r"[,;]+", tech_stack) if t.strip()]
            for item in tech_items:
                if is_exempt(item):
                    continue
                if not check_traceability(item):
                    unverified_items.append({
                        "item": item,
                        "location": f"project: {name}"
                    })

    # h) Keyword integration check
    def collect_all_tailored_text_elements(res: dict[str, Any]) -> list[str]:
        elements = []

        if res.get("summary"):
            elements.append(res["summary"])

        for group in res.get("skills_selected", []):
            if isinstance(group, dict):
                elements.append(group.get("category", ""))
            for item in group.get("items", []):
                elements.append(item)

        for proj in res.get("projects", []):
            if isinstance(proj, dict):
                elements.append(proj.get("name", ""))
                elements.append(proj.get("tech_stack", ""))
                elements.extend(proj.get("bullets", []))

        for intern in res.get("internships_selected", []):
            if isinstance(intern, dict):
                elements.append(intern.get("company", ""))
                elements.append(intern.get("role", ""))
                elements.extend(intern.get("bullets", []))

        for edu in res.get("education", []):
            if isinstance(edu, dict):
                elements.append(edu.get("institution", ""))
                elements.append(edu.get("degree", ""))

        for cert in res.get("certifications", []):
            if isinstance(cert, dict):
                elements.append(cert.get("name", ""))
                elements.append(cert.get("issuer", ""))

        for pub in res.get("publications", []):
            if isinstance(pub, dict):
                elements.append(pub.get("title", ""))
                elements.append(pub.get("publisher", ""))

        for opt in res.get("optional_sections", []):
            if isinstance(opt, dict):
                elements.append(opt.get("title", ""))
                for item in opt.get("items", []):
                    if isinstance(item, dict):
                        elements.append(item.get("name", ""))
                        elements.append(item.get("organization", ""))
                        elements.append(item.get("description", ""))
                        elements.extend(item.get("bullets", []))

        print("\n========== KEYWORD VALIDATION ==========")
        print("Collected text elements:")
        for e in elements:
            print("-", e)

        return [el.strip().lower() for el in elements if el and el.strip()]

    def check_keyword_present_in_elements(keyword: str, elements: list[str]) -> bool:
        kw_lower = keyword.strip().lower()
        for el in elements:
            if kw_lower in el:
                return True
        kw_variants = get_word_variants(kw_lower)
        for variant in kw_variants:
            for el in elements:
                if variant in el:
                    return True
        kw_words = [w for w in re.split(r"[^\w\d]+", kw_lower) if len(w) > 2]
        if kw_words:
            for el in elements:
                all_words_found = True
                for word in kw_words:
                    word_found = False
                    for variant in get_word_variants(word):
                        if variant in el:
                            word_found = True
                            break
                    if not word_found:
                        all_words_found = False
                        break
                if all_words_found:
                    return True
        return False

    if selected_keywords:
        all_elements = collect_all_tailored_text_elements(resume)
        missing_keywords = []
        for kw in selected_keywords:
            present = check_keyword_present_in_elements(kw, all_elements)
            logger.info("Validation (Keyword integration check - '%s'): Pass: %s", kw, present)
            if not present:
                missing_keywords.append(kw)
        if missing_keywords:
            errors.append(
                f"Missing user-selected keywords: the following keywords were selected by the user to integrate "
                f"but are completely missing from the generated resume: {', '.join(missing_keywords)}. "
                f"You must integrate all user-selected keywords into appropriate sections (skills, summary, or bullets)."
            )

    # i) Project title verification
    for proj in resume.get("projects", []):
        if not isinstance(proj, dict):
            continue
        ai_name = proj.get("name", "")
        expected_title = find_full_project_title_from_blob(ai_name, master_resume) or ""
        logger.info("Validation (Project title comparison): Tailored Title: '%s' | Expected Master Title: '%s'", ai_name, expected_title)
        if expected_title and ai_name != expected_title:
            errors.append(f"Project title mismatch: tailored project name '{ai_name}' does not match expected master name '{expected_title}'")

    if return_unverified:
        return errors, unverified_items
    return errors


def get_buzzword_suggestions(phrase: str) -> str:
    suggestions = {
        "proven ability": (
            "1. State directly what the candidate did (e.g., instead of 'Proven ability to build APIs', write 'Designed and scaled REST APIs using Python').\n"
            "2. Focus on concrete outcomes (e.g., 'Implemented multi-tenant architectures and optimized SQL database queries')."
        ),
        "proven track record": (
            "1. Focus on actual projects (e.g., instead of 'Proven track record of deploying apps', write 'Containerized and deployed enterprise application stacks').\n"
            "2. State your specific achievements directly."
        ),
        "highly motivated": (
            "1. Start with your technical background (e.g., 'Computer Science graduate with hands-on development experience in Python').\n"
            "2. State your core expertise directly."
        ),
        "results-driven": (
            "1. Focus on achievements (e.g., 'Developed a high-availability backend service resulting in X').\n"
            "2. State what you have designed/shipped."
        ),
        "passionate": (
            "1. State your specific domain interest or skillset directly (e.g., 'Software Engineer specializing in secure backend development').\n"
            "2. Focus on technical competencies."
        ),
        "dynamic": (
            "1. Open with your credentials (e.g., 'Software Engineer with experience across full-stack development')."
        ),
        "hardworking": (
            "1. Open with your technical background."
        ),
        "seeking a challenging opportunity": (
            "1. Skip the objective preamble entirely and open directly with the candidate's core expertise (e.g., 'Software Engineer with a focus on cloud-native application design')."
        ),
        "fast learner": (
            "1. Focus on hands-on project experience to demonstrate learning capacity implicitly."
        ),
        "team player": (
            "1. Focus on collaboration in your experiences (e.g., 'Collaborated on frontend implementations within agile teams')."
        ),
        "forward-thinking": (
            "1. State the modern technologies you work with."
        ),
        "dedicated": (
            "1. Focus on the results of your work."
        ),
        "proactive": (
            "1. Focus on initiative shown in your bullets/summary."
        ),
        "committed to delivering": (
            "1. State the direct outcomes of your development work."
        )
    }
    return suggestions.get(phrase.lower().strip(), "State directly what the candidate has actually built/done, without any ability/skill-framing preamble at all.")

def deterministic_buzzword_cleanup(summary_text: str) -> str:
    original = summary_text

    # Buzzwords replaced globally across the whole summary.
    # IMPORTANT: "proven ability to <verb>" must become "experience <verb>ing"
    # to avoid leaving broken grammar like "experience in collaborate".
    # We handle it with a special pattern that captures the following verb.
    GLOBAL_REPLACEMENTS = [
        # "proven ability to <verb>" -> "experience <verb>ing" (captures verb)
        (r'\bproven ability to\s+(\w+)', lambda m: f"experience {m.group(1)}ing"),
        (r'\bproven ability\b', 'demonstrated capability'),
        (r'\bproven track record of\b', 'experience in'),
        (r'\bproven track record\b', 'experience'),
        (r'\bcommitted to delivering\b', 'focused on'),
        (r'\bseeking a challenging opportunity\b', ''),
        (r'\bhighly motivated\b', ''),
        (r'\bresults-driven\b', ''),
        (r'\bpassionate\b', ''),
        (r'\bdynamic\b', ''),
        (r'\bhardworking\b', ''),
        (r'\bfast learner\b', ''),
        (r'\bteam player\b', ''),
        (r'\bforward-thinking\b', ''),
        (r'\bdedicated\b', ''),
        (r'\bproactive\b', ''),
    ]

    # "experienced" is ONLY stripped at the very start of the summary or
    # at the start of a new sentence (after ". "). Stripping it mid-sentence
    # breaks grammar e.g. "Experienced in conducting log analysis" mid-para
    # becomes " in conducting log analysis" — a broken fragment.
    # So we do NOT touch "experienced" in the global pass at all.

    cleaned = original

    for pattern, repl in GLOBAL_REPLACEMENTS:
        if callable(repl):
            # Lambda replacement — handles verb capture
            cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)
        else:
            def repl_func(match, repl=repl):
                if not repl:
                    return ""
                val = match.group(0)
                if val[0].isupper():
                    return repl[0].upper() + repl[1:]
                return repl
            cleaned = re.sub(pattern, repl_func, cleaned, flags=re.IGNORECASE)

    # Strip "experienced" ONLY at sentence boundaries:
    # — at position 0 (start of summary)
    # — immediately after ". " (start of a new sentence mid-paragraph)
    # Split on sentence boundaries, strip from each sentence's opener, rejoin.
    def strip_experienced_from_sentence_openers(text: str) -> str:
        # Split into sentences on ". " boundaries, preserving the delimiter
        parts = re.split(r'(\.\s+)', text)
        result = []
        for i, part in enumerate(parts):
            # Every even index (0, 2, 4...) is a sentence chunk
            # Every odd index is the ". " delimiter
            if i % 2 == 0:
                # Strip "experienced" only at the very start of this sentence chunk
                part = re.sub(
                    r'^experienced\b\s*',
                    '',
                    part,
                    flags=re.IGNORECASE
                )
                # Strip dangling opener left behind e.g. "in conducting..."
                part = re.sub(
                    r'^(in|on|with|for|to|of|at|by|as|and|but|or|within|across|'
                    r'through|via|about|around|between|into|from|under|over|along|'
                    r'during|while|when|if|although|because|since|after|before|'
                    r'that|which|whose|who)\s+',
                    '',
                    part.strip(),
                    flags=re.IGNORECASE
                )
                # Capitalize the first letter of each sentence
                if part:
                    part = part[0].upper() + part[1:]
            result.append(part)
        return ''.join(result)

    cleaned = strip_experienced_from_sentence_openers(cleaned)

    cleaned = re.sub(r'\s+', ' ', cleaned)

    def capitalize_sentence_starts(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        text = text[0].upper() + text[1:]
        text = re.sub(r'\.\s+([a-z])', lambda m: ". " + m.group(1).upper(), text)
        return text

    cleaned = capitalize_sentence_starts(cleaned)
    cleaned = re.sub(r'\s*,\s*,', ',', cleaned)
    cleaned = re.sub(r'\s*-\s*-', '-', cleaned)
    cleaned = re.sub(r'\s*,\s*\.', '.', cleaned)
    cleaned = re.sub(r'^\s*[-–—,\.]+\s*', '', cleaned)
    cleaned = cleaned.strip()

    return cleaned


def classify_skills_with_llm(client: Any, skills_list: list[str]) -> dict[str, str]:
    """
    Batches skill items and calls Gemini to classify each as TECHNICAL_SKILL or NOT_A_SKILL.
    Returns a mapping of {original_item: classification}.
    """
    print(f"[UNCONDITIONAL_LOG] classify_skills_with_llm: Sent for classification: {skills_list}")
    logger.info("classify_skills_with_llm: Sent for classification: %s", skills_list)
    if not skills_list:
        print("[UNCONDITIONAL_LOG] classify_skills_with_llm: empty skills list. Returning empty mapping.")
        return {}

    system_instruction = (
        "You are an expert technical resume parser and auditor. Your task is to classify "
        "a list of proposed resume skill tags as either TECHNICAL_SKILL or NOT_A_SKILL.\n\n"
        "Classification Rules:\n"
        "1. TECHNICAL_SKILL: Must be a concrete, nameable, learnable technical noun: "
        "a programming language, framework, library, developer tool, platform, protocol, "
        "database, cloud service, or a recognized named technical methodology/certification "
        "(e.g., 'SDLC', 'STLC', 'RBAC', 'Regression Testing', 'CI/CD', 'REST API', 'Wireshark', 'Docker').\n"
        "2. NOT_A_SKILL: Any of the following:\n"
        "   - Generic job-duty or testing-activity phrases (e.g., 'Test Plans', 'Test Plan Development', 'Test Case Design', 'Bug Tracking', 'Defect Documentation', 'Log Analysis', 'Troubleshooting', 'Functional Tests', 'Functional Testing', 'System Level Testing', 'Manual Testing', 'Integration Testing', 'Software Testing').\n"
        "   - Bare, vague, or overly broad nouns with no specific technical referent (e.g., 'Security' alone, 'Encryption' alone, 'Software' alone, 'Hardware' alone, 'Quality' alone, 'Testing' alone, 'Development' alone).\n"
        "   - Soft skills or gerund/verb-based activities (e.g., 'Communication', 'Collaboration', 'Problem Solving', 'Time Management', 'Stakeholder Communication', 'Requirements Gathering').\n\n"
        "You must return a valid JSON list of objects matching this exact schema \u2014 no markdown, no prose, no code fences:\n"
        "[\n"
        "  {\n"
        "    \"item\": \"<string>\",\n"
        "    \"classification\": \"TECHNICAL_SKILL\" | \"NOT_A_SKILL\"\n"
        "  }\n"
        "]"
    )

    prompt = f"Please classify the following proposed skill items:\n{json.dumps(skills_list, indent=2)}"

    try:
        # Route through the same multi-model retry/fallback chain used everywhere
        # else in this file, instead of a single unprotected model call. This is
        # what makes classification actually run reliably for ANY resume/JD,
        # instead of silently no-oping on a transient error.
        response = generate_content_with_fallback(
            client=client,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.0,
        )
        cleaned = _strip_markdown_fences(response.text)
        data = json.loads(cleaned)

        mapping = {}
        if isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict) and "item" in obj and "classification" in obj:
                    mapping[obj["item"].strip()] = obj["classification"].strip()
        print(f"[UNCONDITIONAL_LOG] classify_skills_with_llm: API Call SUCCEEDED. Mapping: {mapping}")
        logger.info("classify_skills_with_llm: API Call SUCCEEDED. Mapping: %s", mapping)
        return mapping
    except Exception as exc:
        print(f"[UNCONDITIONAL_LOG] classify_skills_with_llm: API Call FAILED. Exception: {exc}")
        logger.exception("Error in classify_skills_with_llm: %s", exc)
        return {}


def filter_non_skills_via_classification(client: Any, tailored_data: dict[str, Any], selected_keywords: list[str] | None = None):
    resume = tailored_data.get("tailored_resume", {})
    skills_selected = resume.get("skills_selected", [])

    HARD_BLOCKED_SKILL_TERMS = {
        "manual testing", "regression testing", "defect documentation", "bug tracking",
        "log analysis", "troubleshooting", "functional tests", "functional testing",
        "sdlc", "stlc", "test plans", "test plan development", "test case design",
        "systems test engineering", "software testing", "hardware testing",
        "integration testing", "system level testing", "quality assurance",
        "defect tracking", "issue tracking", "test execution", "test reporting"
    }

    # Apply hard block FIRST — strip known non-technical terms deterministically
    # before sending anything to the LLM classifier.
    for group in skills_selected:
        if isinstance(group, dict):
            group["items"] = [
                item for item in group.get("items", [])
                if item.strip().lower() not in HARD_BLOCKED_SKILL_TERMS
            ]

    # Collect all_skills AFTER hard block — so the LLM never even sees
    # hard-blocked terms, eliminating inconsistent classifications for
    # terms like 'Regression Testing' that the LLM sometimes gets wrong.
    all_skills = []
    for group in skills_selected:
        if isinstance(group, dict):
            for item in group.get("items", []):
                if isinstance(item, str) and item.strip():
                    all_skills.append(item.strip())

    print(f"[UNCONDITIONAL_LOG] filter_non_skills_via_classification: CALLED with {len(all_skills)} items")
    logger.info("filter_non_skills_via_classification: CALLED with %d items", len(all_skills))

    if not skills_selected:
        print("[UNCONDITIONAL_LOG] filter_non_skills_via_classification: skills_selected is empty. No filtering needed.")
        return

    if not all_skills:
        print("[UNCONDITIONAL_LOG] filter_non_skills_via_classification: all_skills is empty after hard block. No LLM classification needed.")
        # Still remove empty categories
        resume["skills_selected"] = [
            group for group in skills_selected
            if isinstance(group, dict) and group.get("items")
        ]
        return

    classifications = classify_skills_with_llm(client, list(set(all_skills)))

    if not classifications:
        print("[UNCONDITIONAL_LOG] filter_non_skills_via_classification: Fail-safe fallback triggered because classifications mapping is empty (API failure). No skills stripped.")
        logger.warning("filter_non_skills_via_classification: Fail-safe fallback triggered because classifications mapping is empty (API failure). No skills stripped.")
        # Still remove empty categories even on fallback
        resume["skills_selected"] = [
            group for group in skills_selected
            if isinstance(group, dict) and group.get("items")
        ]
        return

    filtered_groups = []
    for group in skills_selected:
        if not isinstance(group, dict):
            filtered_groups.append(group)
            continue

        category = group.get("category", "")
        items = group.get("items", [])
        new_items = []
        for item in items:
            if not isinstance(item, str):
                new_items.append(item)
                continue

            item_strip = item.strip()
            cls = classifications.get(item_strip, "TECHNICAL_SKILL")
            if cls == "NOT_A_SKILL":
                is_user_selected = False
                if selected_keywords:
                    item_clean = item_strip.lower()
                    for kw in selected_keywords:
                        kw_clean = kw.strip().lower()
                        if item_clean == kw_clean or (item_clean.endswith('s') and item_clean[:-1] == kw_clean) or (kw_clean.endswith('s') and kw_clean[:-1] == item_clean):
                            is_user_selected = True
                            break
                print(f"[UNCONDITIONAL_LOG] filter_non_skills_via_classification: Stripped non-technical skill item: '{item}' (even if user-selected — belongs in bullets only)")
                logger.info("Stripped non-technical skill item via LLM classification: '%s'", item)
            else:
                new_items.append(item)

        # Only keep this category if it still has items after filtering
        if new_items:
            new_group = dict(group)
            new_group["items"] = new_items
            filtered_groups.append(new_group)
        else:
            print(f"[UNCONDITIONAL_LOG] filter_non_skills_via_classification: Dropped empty category '{category}' after filtering.")
            logger.info("Dropped empty skill category '%s' — all items were non-technical.", category)

    resume["skills_selected"] = filtered_groups


def deduplicate_skills_selected(skills_selected: list[Any]) -> list[Any]:
    if not skills_selected:
        return skills_selected
        
    def are_near_duplicates(item1: str, item2: str) -> bool:
        i1 = item1.strip().lower()
        i2 = item2.strip().lower()
        if i1 == i2:
            return True
        if i1.endswith('s') and i1[:-1] == i2:
            return True
        if i2.endswith('s') and i2[:-1] == i1:
            return True
        return False

    # 1. Within-category deduplication
    deduped_groups = []
    for group in skills_selected:
        if not isinstance(group, dict):
            deduped_groups.append(group)
            continue
            
        category = group.get("category", "")
        items = group.get("items", [])
        if not items:
            deduped_groups.append(group)
            continue
            
        seen_items = []
        for item in items:
            if not isinstance(item, str):
                seen_items.append(item)
                continue
                
            is_dup = False
            for seen in seen_items:
                if isinstance(seen, str) and are_near_duplicates(item, seen):
                    is_dup = True
                    break
            if not is_dup:
                seen_items.append(item)
                
        new_group = dict(group)
        new_group["items"] = seen_items
        deduped_groups.append(new_group)

    # 2. Cross-category deduplication
    known_languages = {"python", "java", "javascript", "c", "c++", "c#", "php", "typescript", "go", "rust", "ruby", "swift", "kotlin", "html", "css"}
    
    seen_cross = {}
    for idx, group in enumerate(deduped_groups):
        if not isinstance(group, dict):
            continue
        items = group.get("items", [])
        for item in items:
            if not isinstance(item, str):
                continue
            item_norm = item.strip().lower()
            if item_norm.endswith('s'):
                sing = item_norm[:-1]
            else:
                sing = item_norm
                
            found_key = None
            for key in seen_cross:
                if key == sing or (key.endswith('s') and key[:-1] == sing) or (sing.endswith('s') and sing[:-1] == key):
                    found_key = key
                    break
            if found_key is None:
                found_key = item_norm
                seen_cross[found_key] = []
            seen_cross[found_key].append((idx, item))
            
    for key, occurrences in seen_cross.items():
        if len(occurrences) > 1:
            best_idx = 0
            if key in known_languages or (key.endswith('s') and key[:-1] in known_languages):
                # Search for a category name containing 'language' or 'programming'
                for i, (g_idx, item) in enumerate(occurrences):
                    cat_name = deduped_groups[g_idx].get("category", "").lower()
                    if "language" in cat_name or "programming" in cat_name or "code" in cat_name:
                         best_idx = i
                         break
            keep_g_idx, keep_item = occurrences[best_idx]
            for i, (g_idx, item) in enumerate(occurrences):
                if i != best_idx:
                    group = deduped_groups[g_idx]
                    group["items"] = [x for x in group["items"] if not are_near_duplicates(x, item)]
                    
    return deduped_groups

