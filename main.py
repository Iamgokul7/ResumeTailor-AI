"""
main.py — FastAPI application for ResumeTailor.

Endpoints:
  POST /api/generate-resume   — Accept JD text, call Gemini, run safety check, return result + PDF path.
  GET  /api/download/{fname}  — Stream the generated PDF to the browser.
  GET  /                      — Serve the single-page frontend.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import os
import collections
import time
import threading
from pydantic import BaseModel

load_dotenv()

from gemini_service import tailor_resume, analyze_jd_match
from pdf_service import render_pdf
from storage import get_all_keywords

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="ResumeTailor", version="1.0.0")

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Load and validate environment variables
SESSION_SECRET = os.environ.get("SESSION_SECRET")
SITE_PASSWORDS_RAW = os.environ.get("SITE_PASSWORDS")

if not SESSION_SECRET or not SITE_PASSWORDS_RAW:
    if os.environ.get("RENDER"):
        raise ValueError("Production configuration error: SESSION_SECRET and SITE_PASSWORDS must be set in environment variables.")
    else:
        # Development fallback
        if not SESSION_SECRET:
            SESSION_SECRET = "dev-session-secret-key-change-in-production"
            logger.warning("SESSION_SECRET is not set. Using fallback key for development.")
        if not SITE_PASSWORDS_RAW:
            SITE_PASSWORDS_RAW = "admin"
            logger.warning("SITE_PASSWORDS is not set. Using default password 'admin' for development.")

# ---------------------------------------------------------------------------
# Rate Limiting for Login
# ---------------------------------------------------------------------------
login_failures = collections.defaultdict(list)
login_failures_lock = threading.Lock()

def check_login_rate_limit(ip: str) -> bool:
    """Returns True if rate limit is NOT exceeded (i.e. okay to proceed)."""
    now = time.time()
    ten_minutes_ago = now - 600
    with login_failures_lock:
        login_failures[ip] = [t for t in login_failures[ip] if t > ten_minutes_ago]
        if len(login_failures[ip]) >= 5:
            return False
    return True

def record_login_failure(ip: str):
    with login_failures_lock:
        login_failures[ip].append(time.time())

def reset_login_failures(ip: str):
    with login_failures_lock:
        if ip in login_failures:
            del login_failures[ip]

def verify_password(entered_password: str) -> bool:
    if not SITE_PASSWORDS_RAW:
        return False
    allowed_passwords = [p.strip() for p in SITE_PASSWORDS_RAW.split(",") if p.strip()]
    return entered_password.strip() in allowed_passwords

# ---------------------------------------------------------------------------
# Route Guard Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # 1. Allowed paths that bypass authentication
    is_login_route = (path == "/login")
    is_static_asset = (path.startswith("/static/") and not path.endswith("index.html"))
    is_favicon = (path == "/favicon.ico")
    
    if is_login_route or is_static_asset or is_favicon:
        return await call_next(request)
        
    # 2. Check session authentication status
    is_authenticated = request.session.get("authenticated", False)
    if is_authenticated:
        return await call_next(request)
        
    # 3. Handle unauthenticated requests
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    else:
        return RedirectResponse(url="/login")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Mount static files (JS, CSS, etc.)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    master_resume: str
    jd_text: str


class AnalyzeResponse(BaseModel):
    overall_match_percentage: int
    matched_requirements: list[str]
    missing_requirements: list[str]
    experience_level_fit: str
    master_keywords: list[str]
    jd_keywords: list[str]
    keyword_alignments: list[dict[str, Any]]


class GenerateRequest(BaseModel):
    master_resume: str
    jd_text: str
    selected_keywords: list[str]


class GenerateResponse(BaseModel):
    tailored: dict[str, Any]
    pdf_filename: str
    overall_match_percentage: int
    warnings: list[str] = []
    dashboard: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Fabrication safety check
# ---------------------------------------------------------------------------

# Minimum token length to bother checking (ignore very short words like "a", "of")
_MIN_TOKEN_LEN = 3

# Words that are so generic they're never a "fabricated skill"
_STOPWORDS = {
    "and", "the", "for", "with", "using", "from", "into", "that",
    "this", "each", "their", "which", "have", "been", "will", "per",
    "our", "all", "are", "was", "were", "its", "not", "but", "can",
    "new", "via", "any", "add", "set", "run", "key", "top", "end",
    "one", "two", "api", "sub",
}


def _normalize_text(text: str) -> str:
    """Normalize text for robust comparison by lowercasing, normalizing hyphens, and collapsing spaces."""
    if not text:
        return ""
    text = text.lower()
    # Normalize hyphens: replace " - " or "  -  " with "-"
    text = re.sub(r"\s*-\s*", "-", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _build_bank_text(bank: dict[str, Any]) -> str:
    """Flatten the entire bank into one lowercase string for phrase search."""
    parts: list[str] = []

    def _collect(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj.lower())
        elif isinstance(obj, dict):
            for v in obj.values():
                _collect(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)

    _collect(bank)
    return " ".join(parts)


def _extract_skill_items(tailored: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Return (full_item_string, source_label) pairs for every skill item
    and tech_stack entry in the tailored output.
    We check whole items (e.g. "PostgreSQL", "GitHub Actions") rather than
    splitting them into sub-tokens, which prevents short generic tokens
    from masking invented multi-word terms.
    """
    results: list[tuple[str, str]] = []

    for entry in tailored.get("skills_selected", []):
        cat = entry.get("category", "")
        for item in entry.get("items", []):
            item_str = item.strip()
            if len(item_str) >= _MIN_TOKEN_LEN:
                results.append((item_str, f"skills[{cat}]"))

    for key in ["projects_selected", "flagship_projects_selected", "other_projects_selected"]:
        for proj in tailored.get(key, []):
            stack = proj.get("tech_stack", "")
            for part in re.split(r"[,;]+", stack):
                part = part.strip()
                if len(part) >= _MIN_TOKEN_LEN:
                    results.append((part, f"project[{proj.get('name', '')}].tech_stack"))

    return results


def run_fabrication_check(
    tailored: dict[str, Any],
    bank: dict[str, Any],
) -> list[str]:
    """
    Compare every skill/tech item in *tailored* against the full bank text.

    Strategy:
    1. Build a single lowercase string of all bank content.
    2. For each skill item (e.g. "PostgreSQL", "GitHub Actions"):
       a. Check if the lowercased item appears as a substring in the bank text.
       b. If not, also check each individual word token of the item against
          the bank keyword set (catches abbreviations like "AWS", "GCP").
    3. If neither check passes -> flag as a possible fabrication.

    Returns a list of warning strings. Empty list = all clear.
    """
    bank_text = _build_bank_text(bank)
    bank_text_norm = _normalize_text(bank_text)
    bank_keywords = get_all_keywords(bank)
    bank_keywords_norm = {_normalize_text(k) for k in bank_keywords}
    
    warnings: list[str] = []
    seen: set[str] = set()

    for item, source in _extract_skill_items(tailored):
        item_lower = item.lower()

        # Skip pure stopwords
        if item_lower in _STOPWORDS:
            continue

        # Primary check: whole item present in bank text (substring match on normalized text)
        item_norm = _normalize_text(item)
        if item_norm in bank_text_norm:
            continue

        # Secondary check: split into tokens — ALL meaningful tokens must be
        # known in the bank keyword set (exact match) or in bank text.
        tokens = [
            t.strip(".-").lower()
            for t in re.split(r"[\s,;/()\[\]\"']+", item)
            if len(t.strip(".-")) >= _MIN_TOKEN_LEN
            and t.strip(".-").lower() not in _STOPWORDS
        ]
        
        # Normalize tokens for comparison
        tokens_norm = [_normalize_text(t) for t in tokens]

        def _token_known(tok: str) -> bool:
            return tok in bank_keywords_norm or tok in bank_text_norm

        all_tokens_known = all(_token_known(t) for t in tokens_norm) if tokens_norm else True

        if not all_tokens_known:
            if item_lower not in seen:
                seen.add(item_lower)
                logger.warning("Possible fabricated skill: '%s' (from %s)", item, source)
                warnings.append(item)

    return warnings



# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    if request.session.get("authenticated", False):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def post_login(request: Request, password: str = Form(...)):
    ip = request.client.host if request.client else "127.0.0.1"
    
    if not check_login_rate_limit(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Too many failed login attempts. Please try again in 10 minutes."},
            status_code=429
        )
        
    if verify_password(password):
        reset_login_failures(ip)
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    else:
        record_login_failure(ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Incorrect password. Please try again."},
            status_code=401
        )


@app.get("/logout")
async def get_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    """Serve the main single-page application."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.post("/api/analyze-keywords", response_model=AnalyzeResponse)
async def analyze_keywords(req: AnalyzeRequest):
    """
    Step 1: Analyze the JD against the master resume.
    Extract match percentage, matched/missing requirements, and keywords.
    """
    if not req.master_resume or len(req.master_resume.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Master resume is too short. Please paste your full resume content.",
        )

    if not req.jd_text or len(req.jd_text.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Job description is too short. Please paste the full JD.",
        )

    try:
        match_analysis = analyze_jd_match(req.master_resume, req.jd_text)
    except Exception as exc:
        logger.exception("Unexpected error calling Gemini Match Analysis")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error during match analysis: {exc}",
        )

    return AnalyzeResponse(
        overall_match_percentage=match_analysis.get("overall_match_percentage", 0),
        matched_requirements=match_analysis.get("matched_requirements", []),
        missing_requirements=match_analysis.get("missing_requirements", []),
        experience_level_fit=match_analysis.get("experience_level_fit", ""),
        master_keywords=match_analysis.get("master_keywords", []),
        jd_keywords=match_analysis.get("jd_keywords", []),
        keyword_alignments=match_analysis.get("keyword_alignments", []),
    )


def find_header_index(text: str, header: str) -> int:
    text_lower = text.lower()
    h_lower = header.lower().strip()
    
    # Try finding with newline prefix
    idx = text_lower.find("\n" + h_lower)
    if idx != -1:
        return idx + 1
        
    # If not found, check if it's at the very beginning of the document
    if text_lower.startswith(h_lower):
        return 0
        
    # Check for space prefix
    idx = text_lower.find(" " + h_lower)
    if idx != -1:
        return idx + 1
        
    return text_lower.find(h_lower)


def check_pdf_linearity_and_completeness(pdf_path: Path, expected_name: str, tailored: dict[str, Any]) -> tuple[bool, str]:
    """
    Extract text from the rendered PDF and verify:
    1. Candidate name is present.
    2. Expected section headers are present in top-to-bottom (linear) order.
    """
    import pypdf
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        extracted_text = "\n".join(text_parts)
    except Exception as exc:
        logger.exception("Error extracting text from generated PDF")
        return False, f"Could not read text from generated PDF: {exc}"

    extracted_lower = extracted_text.lower()
    
    # Verify candidate name (case-insensitive)
    name_norm = expected_name.lower().strip()
    if name_norm not in extracted_lower:
        return False, f"Candidate name '{expected_name}' missing from PDF text layer"

    # Define the expected section headers and check their order using variants
    expected_headers = []
    
    if tailored.get("summary"):
        expected_headers.append(("summary", ["professional summary", "summary"]))
    if tailored.get("skills_selected"):
        expected_headers.append(("skills", ["technical skills", "skills"]))
    if tailored.get("flagship_projects_selected"):
        expected_headers.append(("flagship_projects", ["flagship projects"]))
    if tailored.get("other_projects_selected"):
        expected_headers.append(("other_projects", ["other projects"]))
    if tailored.get("internships_selected"):
        expected_headers.append(("internships", ["internship experience", "work experience", "experience"]))
    if tailored.get("education"):
        expected_headers.append(("education", ["education"]))
    if tailored.get("certifications"):
        expected_headers.append(("certifications", ["certifications"]))

    # Check that headers appear in monotonic index order
    last_idx = -1
    for name, variants in expected_headers:
        idx = -1
        matched_variant = ""
        for var in variants:
            idx = find_header_index(extracted_text, var)
            if idx != -1:
                matched_variant = var
                break
        if idx == -1:
            return False, f"Required section header for '{name}' (expected one of: {variants}) missing from PDF text layer"
        if idx < last_idx:
            return False, f"PDF layout parsed out of order: '{matched_variant}' appeared before previous section"
        last_idx = idx

    return True, ""


@app.post("/api/generate-resume", response_model=GenerateResponse)
async def generate_resume(req: GenerateRequest):
    """
    Step 2: Generate the tailored resume incorporating the selected keywords.
    """
    if not req.master_resume or len(req.master_resume.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Master resume is too short. Please paste your full resume content.",
        )

    if not req.jd_text or len(req.jd_text.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Job description is too short. Please paste the full JD.",
        )

    try:
        tailored, warnings, dashboard = tailor_resume(req.master_resume, req.jd_text, req.selected_keywords)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error calling Gemini for tailoring")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {exc}",
        )

    contact = tailored.get("contact", {})

    # Final PDF Safety Check: verify all unique factual information from master resume is represented
    try:
        from gemini_service import extract_master_entities, check_completeness
        master_entities = extract_master_entities(req.master_resume)
        completeness_errors = check_completeness(master_entities, tailored)
        if completeness_errors:
            logger.error("Final completeness safety check failed before PDF generation: %s", completeness_errors)
            raise HTTPException(
                status_code=502,
                detail=f"Completeness safety check failed before PDF generation: {', '.join(completeness_errors)}"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error running completeness check before PDF generation")

    # Render PDF (Standard Layout first)
    try:
        pdf_path = render_pdf(tailored, contact, simple_layout=False)
        
        # Verify text extraction & layout order
        is_valid_layout, layout_error = check_pdf_linearity_and_completeness(pdf_path, contact.get("name", ""), tailored)
        if not is_valid_layout:
            logger.warning("Standard PDF layout check failed: %s. Regenerating with simple layout...", layout_error)
            # Regenerate with simpler layout
            pdf_path = render_pdf(tailored, contact, simple_layout=True)
            # Recheck layout
            is_valid_layout_simple, layout_error_simple = check_pdf_linearity_and_completeness(pdf_path, contact.get("name", ""), tailored)
            if not is_valid_layout_simple:
                warnings.append(f"PDF layout check failed: {layout_error_simple}")
    except Exception as exc:
        logger.exception("PDF rendering failed")
        raise HTTPException(status_code=500, detail=f"PDF rendering error: {exc}")

    # Calculate final match score dynamically based on how many selected keywords are present in the final resume
    tailored_items = {item.lower() for item, _ in _extract_skill_items(tailored)}
    matched_count = sum(1 for kw in req.selected_keywords if kw.lower() in tailored_items)
    overall_match = 50
    if req.selected_keywords:
        overall_match = int((matched_count / len(req.selected_keywords)) * 50 + 50)
        overall_match = min(100, max(50, overall_match))

    return GenerateResponse(
        tailored=tailored,
        pdf_filename=pdf_path.name,
        overall_match_percentage=overall_match,
        warnings=warnings,
        dashboard=dashboard
    )


@app.get("/api/download/{filename}")
async def download_pdf(filename: str):
    """Stream the requested PDF to the browser."""
    # Sanitize: only allow alphanumeric + underscore + dot, no path traversal
    if not re.match(r"^[\w\-.]+\.pdf$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    pdf_path = OUTPUT_DIR / filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found.")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


def _extract_text_from_file(filename: str, file_bytes: bytes) -> str:
    """Extract text from a PDF or DOCX file."""
    import io
    import pypdf
    import docx
    
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    
    if ext == "pdf":
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            # Extract links from annotations
            links = []
            for page in reader.pages:
                if "/Annots" in page:
                    for annot in page["/Annots"]:
                        obj = annot.get_object()
                        if "/A" in obj and "/URI" in obj["/A"]:
                            uri = obj["/A"]["/URI"]
                            if uri not in links:
                                links.append(uri)
            
            extracted_text = "\n".join(text_parts).strip()
            if links:
                extracted_text += "\n\nEXTRACTED HYPERLINKS:\n" + "\n".join(f"- {l}" for l in links)
            return extracted_text
        except Exception as exc:
            logger.exception("Error extracting text from PDF")
            raise ValueError("Couldn't read text from this PDF - please make sure it's a text-based PDF, not a scanned image.")
            
    elif ext == "docx":
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text]
            return "\n".join(paragraphs).strip()
        except Exception as exc:
            logger.exception("Error extracting text from DOCX")
            raise ValueError("Couldn't read text from this DOCX file.")
            
    else:
        raise ValueError("Unsupported file format. Please upload a PDF or DOCX file.")


@app.post("/api/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """Extract text from the uploaded PDF or DOCX file."""
    filename = file.filename or ""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "docx"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Only PDF and DOCX files are allowed."
        )
        
    try:
        content = await file.read()
        text = _extract_text_from_file(filename, content)
        if len(text.strip()) < 50:
            if ext == "pdf":
                raise ValueError("Couldn't read text from this PDF - please make sure it's a text-based PDF, not a scanned image.")
            else:
                raise ValueError("Couldn't read text from this DOCX file.")
        return {"extracted_text": text}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during file text extraction")
        raise HTTPException(status_code=500, detail=f"Failed to process file: {exc}")
