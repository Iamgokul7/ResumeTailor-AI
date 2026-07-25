"""
main.py — FastAPI application for ResumeTailor.

Endpoints:
  POST /api/generate-resume   — Accept JD text, call Gemini, run safety check, return result + PDF path.
  GET  /api/download/{fname}  — Stream the generated PDF to the browser.
  GET  /                      — Serve the single-page frontend.
"""

from __future__ import annotations

import json
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

from gemini_service import generate_tailored_resume, analyze_jd_match
from pdf_service import render_pdf

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
    
    is_login_route = (path == "/login")
    is_static_asset = (path.startswith("/static/") and not path.endswith("index.html"))
    is_favicon = (path == "/favicon.ico")
    
    if is_login_route or is_static_asset or is_favicon:
        return await call_next(request)
        
    is_authenticated = request.session.get("authenticated", False)
    if is_authenticated:
        return await call_next(request)
        
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
    unverified_skills: list[dict[str, Any]] = []


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
        # Call the new generate_tailored_resume function
        result = generate_tailored_resume(req.master_resume, req.jd_text, req.selected_keywords)
        tailored = result["tailored_resume"]
        # Duplicate projects to projects_selected to ensure frontend UI preview displays it correctly
        tailored["projects_selected"] = tailored.get("projects", [])
        dashboard = result["dashboard"]
        
        warnings = []
        if result.get("dashboard_fallback_used"):
            warnings.append("Dashboard fallback object was used due to malformed or missing dashboard in AI output.")

    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error calling Gemini for tailoring")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {exc}",
        )

    contact = tailored.get("contact", {})

    # Render PDF (only standard layout)
    print("\n========== MAIN.PY ==========")

    print("Section order:")
    print(tailored.get("section_order"))

    print("\nProjects:")
    for p in tailored.get("projects", []):
        print("-", p.get("name"), "|", p.get("section"))

    print("\nPublications:")
    for pub in tailored.get("publications", []):
        print("-", pub.get("title"))
    try:
        pdf_path = render_pdf(tailored, contact)
    except Exception as exc:
        logger.exception("PDF rendering failed")
        raise HTTPException(status_code=500, detail=f"PDF rendering error: {exc}")

    # Calculate overall match percentage
    tailored_text = ""
    for group in tailored.get("skills_selected", []):
        if isinstance(group, dict):
            tailored_text += " " + " ".join(group.get("items", []))
    for proj in tailored.get("projects", []):
        if isinstance(proj, dict):
            tailored_text += " " + proj.get("tech_stack", "") + " " + " ".join(proj.get("bullets", []))
    tailored_text_lower = tailored_text.lower()
    
    matched_count = 0
    if req.selected_keywords:
        for kw in req.selected_keywords:
            if kw.strip().lower() in tailored_text_lower:
                matched_count += 1
        overall_match = int((matched_count / len(req.selected_keywords)) * 50 + 50)
        overall_match = min(100, max(50, overall_match))
    else:
        overall_match = 50

    return GenerateResponse(
        tailored=tailored,
        pdf_filename=pdf_path.name,
        overall_match_percentage=overall_match,
        warnings=warnings,
        dashboard=dashboard,
        unverified_skills=result.get("unverified_skills", [])
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
