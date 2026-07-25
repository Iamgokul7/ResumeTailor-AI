/* ================================================================
   ResumeTailor – app.js
   Handles: form submission, API calls, loading steps animation,
   preview rendering, fabrication warning display, PDF download,
   plain-text copy.
================================================================ */

"use strict";

// ── State ─────────────────────────────────────────────────────
let currentResult = null;   // last API response
let currentPdfFilename = null;
let masterResumeText = null; // extracted text layer from PDF/DOCX
let masterKeywords = [];
let jdKeywords = [];
let keywordAlignments = [];
let selectedMasterKeywords = new Set();
let selectedJdKeywords = new Set();
let initialMatchFitNote = "";

// ── DOM refs (resolved lazily to avoid "null on load" errors) ──
const $ = id => document.getElementById(id);

// Original upload zone HTML — saved at page load, restored when user removes file
let _origUploadZoneHTML = null;

// ── Setup listeners ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const jdTextarea = $("jd-input");
  const jdCounter  = $("jd-char-count");

  if (jdTextarea && jdCounter) {
    jdTextarea.addEventListener("input", () => {
      const n = jdTextarea.value.length;
      jdCounter.textContent = `${n.toLocaleString()} character${n !== 1 ? "s" : ""}`;
    });
  }

  // Save the original upload zone HTML so we can restore it after a reset
  const uploadZone = $("upload-zone");
  if (uploadZone) {
    _origUploadZoneHTML = uploadZone.innerHTML;
    ["dragenter", "dragover"].forEach(eventName => {
      uploadZone.addEventListener(eventName, e => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.add("dragover");
      }, false);
    });

    ["dragleave", "drop"].forEach(eventName => {
      uploadZone.addEventListener(eventName, e => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove("dragover");
      }, false);
    });

    uploadZone.addEventListener("drop", e => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files && files.length > 0) {
        handleFile(files[0]);
      }
    }, false);
  }
});

// ── Section visibility helpers ────────────────────────────────
function showSection(id) {
  ["input-section", "keyword-section", "loading-section", "error-section", "result-section"]
    .forEach(s => {
      const el = $(s);
      if (el) el.classList.add("hidden");
    });
  const el = $(id);
  if (el) el.classList.remove("hidden");
}

function resetToInput() {
  showSection("input-section");
  $("generate-btn").disabled = false;
}

// ── Loading step animation ────────────────────────────────────
let _loadingStepIndex = 0;
let _loadingTimer     = null;

function startLoadingSteps() {
  const steps = ["step-gemini", "step-pdf"];
  _loadingStepIndex = 0;
  steps.forEach(id => {
    const el = $(id);
    if (el) el.classList.remove("active", "done");
  });
  const first = $(steps[0]);
  if (first) first.classList.add("active");

  _loadingTimer = setInterval(() => {
    // Mark current as done
    const curEl = $(steps[_loadingStepIndex]);
    if (curEl) { curEl.classList.remove("active"); curEl.classList.add("done"); }
    _loadingStepIndex++;
    if (_loadingStepIndex < steps.length) {
      const nextEl = $(steps[_loadingStepIndex]);
      if (nextEl) nextEl.classList.add("active");
    } else {
      clearInterval(_loadingTimer);
    }
  }, 4000);  // advance every 4 s (generous — real calls may be slower)
}

function stopLoadingSteps() {
  clearInterval(_loadingTimer);
  ["step-gemini", "step-pdf"].forEach(id => {
    const el = $(id);
    if (el) {
      el.classList.remove("active");
      el.classList.add("done");
    }
  });
}

// ── Step 1: Analyze Keywords ──────────────────────────────────
async function analyzeKeywords() {
  const jdText = $("jd-input").value.trim();

  if (!masterResumeText || masterResumeText.trim().length < 50) {
    showToast("Please upload your existing resume first.", "error");
    return;
  }

  if (!jdText || jdText.length < 50) {
    showToast("Please paste a full job description (at least 50 characters).", "error");
    return;
  }

  $("generate-btn").disabled = true;
  
  const loadTitle = document.querySelector(".loading-title");
  if (loadTitle) loadTitle.textContent = "Analyzing job description and keywords...";
  $("loading-steps").style.display = "none";
  showSection("loading-section");

  try {
    const response = await fetch("/api/analyze-keywords", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ master_resume: masterResumeText, jd_text: jdText }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `Server error ${response.status}`);
    }

    const data = await response.json();
    
    // Save to state
    masterKeywords = data.master_keywords || [];
    jdKeywords = data.jd_keywords || [];
    keywordAlignments = data.keyword_alignments || [];
    initialMatchFitNote = data.experience_level_fit || "";
    
    // Initialize selected master keywords (all by default)
    selectedMasterKeywords.clear();
    masterKeywords.forEach(kw => {
      selectedMasterKeywords.add(kw.toLowerCase());
    });

    // Initialize selected JD keywords (matches by default)
    selectedJdKeywords.clear();
    keywordAlignments.forEach(align => {
      if ((align.status || "").toLowerCase() === "integrated") {
        selectedJdKeywords.add((align.keyword || "").toLowerCase());
      }
    });

    // Render keyword selector UI
    renderKeywordSelector(data);
    showSection("keyword-section");

  } catch (err) {
    $("error-message").textContent = err.message || "An unexpected error occurred.";
    showSection("error-section");
    $("generate-btn").disabled = false;
  } finally {
    // Reset load elements
    if (loadTitle) loadTitle.textContent = "Tailoring your resume...";
    $("loading-steps").style.display = "flex";
  }
}

// ── Render Keyword Selector ───────────────────────────────────
function renderKeywordSelector(data) {
  $("initial-match-score-value").textContent = `${data.overall_match_percentage}%`;
  
  const scoreValEl = $("initial-match-score-value");
  if (data.overall_match_percentage >= 80) {
    scoreValEl.style.color = "var(--success)";
  } else if (data.overall_match_percentage >= 50) {
    scoreValEl.style.color = "var(--warning)";
  } else {
    scoreValEl.style.color = "var(--danger)";
  }

  $("initial-match-fit-note").innerHTML = `<strong>Experience Fit:</strong> ${escHtml(data.experience_level_fit || "N/A")}`;

  // Box 1, 2 & 3 update
  updateKeywordBoxes();
}

function updateKeywordBoxes() {
  const masterBox = $("box-master-keywords");
  const jdBox = $("box-jd-keywords");
  const tailoredBox = $("box-tailored-keywords");

  masterBox.innerHTML = "";
  jdBox.innerHTML = "";
  tailoredBox.innerHTML = "";

  // Render Box 1: Original Resume Keywords (Interactive)
  if (masterKeywords.length > 0) {
    masterKeywords.forEach(kw => {
      const kwLower = kw.toLowerCase();
      const isSelected = selectedMasterKeywords.has(kwLower);
      const badge = document.createElement("span");
      badge.textContent = kw;
      badge.className = isSelected ? "keyword-badge-interactive state-original-active" : "keyword-badge-interactive state-original-inactive";
      badge.addEventListener("click", () => toggleMasterKeyword(kw));
      masterBox.appendChild(badge);
    });
  } else {
    masterBox.innerHTML = "<span class='text-muted'>None found.</span>";
  }

  // Render Box 2: JD Keywords (Interactive)
  if (jdKeywords.length > 0) {
    jdKeywords.forEach(kw => {
      const kwLower = kw.toLowerCase();
      const alignObj = keywordAlignments.find(a => (a.keyword || "").toLowerCase() === kwLower || kwLower.includes((a.keyword || "").toLowerCase()));
      const isInitialMatch = alignObj ? (alignObj.status === "integrated") : false;
      const isSelected = selectedJdKeywords.has(kwLower);

      const badge = document.createElement("span");
      badge.textContent = kw;
      
      // Classes depending on selection state
      if (isSelected) {
        badge.className = isInitialMatch ? "keyword-badge-interactive state-match-active" : "keyword-badge-interactive state-gap-active";
      } else {
        badge.className = isInitialMatch ? "keyword-badge-interactive state-match-inactive" : "keyword-badge-interactive state-gap-inactive";
      }

      if (alignObj && alignObj.detail) {
        badge.title = alignObj.detail;
      }

      badge.addEventListener("click", () => toggleJdKeyword(kw));
      jdBox.appendChild(badge);
    });
  } else {
    jdBox.innerHTML = "<span class='text-muted'>None found.</span>";
  }

  // Render Box 3: Keywords to Integrate (Union of selected master and selected JD)
  const allIntegrate = new Set();
  
  // Add selected master keywords
  masterKeywords.forEach(kw => {
    if (selectedMasterKeywords.has(kw.toLowerCase())) {
      allIntegrate.add(kw);
    }
  });

  // Add selected JD keywords
  jdKeywords.forEach(kw => {
    if (selectedJdKeywords.has(kw.toLowerCase())) {
      allIntegrate.add(kw);
    }
  });

  if (allIntegrate.size > 0) {
    allIntegrate.forEach(kw => {
      const span = document.createElement("span");
      span.className = "keyword-tag-tailored";
      span.textContent = kw;
      tailoredBox.appendChild(span);
    });
  } else {
    tailoredBox.innerHTML = "<span class='text-muted'>None selected.</span>";
  }
}

function toggleMasterKeyword(kw) {
  const kwLower = kw.toLowerCase();
  if (selectedMasterKeywords.has(kwLower)) {
    selectedMasterKeywords.delete(kwLower);
  } else {
    selectedMasterKeywords.add(kwLower);
  }
  updateKeywordBoxes();
}

function toggleJdKeyword(kw) {
  const kwLower = kw.toLowerCase();
  if (selectedJdKeywords.has(kwLower)) {
    selectedJdKeywords.delete(kwLower);
  } else {
    selectedJdKeywords.add(kwLower);
  }
  updateKeywordBoxes();
}

// ── Step 2: Generate Tailored Resume ─────────────────────────
async function generateTailoredResume() {
  const jdText = $("jd-input").value.trim();

  showSection("loading-section");
  startLoadingSteps();

  // Combine selected master keywords and selected JD keywords
  const selectedList = [];
  masterKeywords.forEach(kw => {
    if (selectedMasterKeywords.has(kw.toLowerCase())) {
      selectedList.push(kw);
    }
  });
  jdKeywords.forEach(kw => {
    if (selectedJdKeywords.has(kw.toLowerCase()) && !selectedList.includes(kw)) {
      selectedList.push(kw);
    }
  });

  try {
    const response = await fetch("/api/generate-resume", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        master_resume: masterResumeText,
        jd_text: jdText,
        selected_keywords: selectedList
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `Server error ${response.status}`);
    }

    const data = await response.json();
    stopLoadingSteps();

    currentResult      = data.tailored;
    currentPdfFilename = data.pdf_filename;

    renderResult(data);
    showSection("result-section");

  } catch (err) {
    stopLoadingSteps();
    $("error-message").textContent = err.message || "An unexpected error occurred.";
    showSection("error-section");
  } finally {
    $("generate-btn").disabled = false;
  }
}

// ── Render the result preview ─────────────────────────────────
function renderResult(data) {
  const { tailored, overall_match_percentage, warnings, dashboard } = data;

  // ── Render Warnings ──
  const warnContainer = $("warnings-container");
  const warnList = $("warnings-list");
  if (warnContainer && warnList) {
    warnList.innerHTML = "";
    if (warnings && warnings.length > 0) {
      warnings.forEach(w => {
        const li = document.createElement("li");
        li.textContent = w;
        warnList.appendChild(li);
      });
      warnContainer.classList.remove("hidden");
    } else {
      warnContainer.classList.add("hidden");
    }
  }

  // ── Render Scoring Dashboard ──
  const dashboardCard = $("dashboard-card");
  if (dashboardCard && dashboard) {
    $("ats-score-val").textContent = `${dashboard.ats_score || 0}%`;
    $("ats-explanation-text").textContent = dashboard.ats_explanation || "";

    $("readability-score-val").textContent = `${dashboard.readability_score || 0}%`;
    $("readability-explanation-text").textContent = dashboard.readability_explanation || "";

    $("capability-score-val").textContent = `${dashboard.match_score || 0}%`;
    $("capability-explanation-text").textContent = dashboard.match_explanation || "";

    const renderList = (elementId, items) => {
      const listEl = $(elementId);
      if (listEl) {
        listEl.innerHTML = "";
        if (items && items.length > 0) {
          items.forEach(item => {
            const li = document.createElement("li");
            li.textContent = item;
            listEl.appendChild(li);
          });
        } else {
          listEl.innerHTML = "<li class='text-muted'>None identified.</li>";
        }
      }
    };

    renderList("strengths-list", dashboard.strengths);
    renderList("weaknesses-list", dashboard.weaknesses);
    renderList("improvements-list", dashboard.improvements);

    dashboardCard.classList.remove("hidden");
  } else if (dashboardCard) {
    dashboardCard.classList.add("hidden");
  }

  // ── Match Analysis Card ──
  const matchCard = $("match-analysis-card");
  if (matchCard) {
    const pct = overall_match_percentage || 0;
    $("match-score-value").textContent = `${pct}%`;
    
    // Change score color dynamically based on percentage
    const scoreValEl = $("match-score-value");
    if (pct >= 80) {
      scoreValEl.style.color = "var(--success)";
    } else if (pct >= 50) {
      scoreValEl.style.color = "var(--warning)";
    } else {
      scoreValEl.style.color = "var(--danger)";
    }

    $("match-fit-note").innerHTML = `<strong>Experience Fit:</strong> ${escHtml(initialMatchFitNote || "N/A")}`;

    // Render matches list (based on selected keywords)
    const mList = $("match-list");
    mList.innerHTML = "";
    const matches = jdKeywords.filter(k => selectedJdKeywords.has(k.toLowerCase()));
    if (matches.length > 0) {
      matches.forEach(req => {
        const li = document.createElement("li");
        li.textContent = req;
        mList.appendChild(li);
      });
    } else {
      mList.innerHTML = "<li>No matched requirements selected.</li>";
    }

    // Render gaps list (based on unselected keywords)
    const gList = $("gap-list");
    gList.innerHTML = "";
    const gaps = jdKeywords.filter(k => !selectedJdKeywords.has(k.toLowerCase()));
    if (gaps.length > 0) {
      gaps.forEach(req => {
        const li = document.createElement("li");
        li.textContent = req;
        gList.appendChild(li);
      });
    } else {
      gList.innerHTML = "<li>No gaps identified.</li>";
    }

    matchCard.classList.remove("hidden");
  } else if (matchCard) {
    matchCard.classList.add("hidden");
  }

  // ── Contact Info ──
  const contactEl = $("preview-contact");
  if (contactEl && tailored.contact) {
    const c = tailored.contact;
    const infoParts = [];
    if (c.email) infoParts.push(escHtml(c.email));
    if (c.phone) infoParts.push(escHtml(c.phone));
    if (c.location) infoParts.push(escHtml(c.location));
    
    const linkParts = [];
    if (c.linkedin) linkParts.push(`<a href="${escHtml(c.linkedin)}" target="_blank" rel="noopener" class="preview-link">LinkedIn</a>`);
    if (c.github) linkParts.push(`<a href="${escHtml(c.github)}" target="_blank" rel="noopener" class="preview-link">GitHub</a>`);
    if (c.portfolio) linkParts.push(`<a href="${escHtml(c.portfolio)}" target="_blank" rel="noopener" class="preview-link">Portfolio</a>`);

    contactEl.innerHTML = `
      <div class="preview-contact-header" style="text-align: center; margin-bottom: 24px; border-bottom: 2px solid var(--border); padding-bottom: 16px;">
        <h1 style="margin: 0 0 8px 0; font-size: 26px; font-weight: 800; color: var(--text-main); text-transform: uppercase; letter-spacing: 0.5px;">${escHtml(c.name || "Your Name")}</h1>
        <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 8px; font-weight: 500;">${infoParts.join(" &nbsp;|&nbsp; ")}</div>
        <div style="font-size: 13px; color: var(--primary); display: flex; justify-content: center; gap: 16px; font-weight: 600;">${linkParts.join("")}</div>
      </div>
    `;
  } else if (contactEl) {
    contactEl.innerHTML = "";
  }

  // ── Summary ──
  const summaryEl = $("preview-summary");
  if (tailored.summary) {
    summaryEl.innerHTML = `
      <div class="preview-section-title">Professional Summary</div>
      <p class="preview-summary-text">${escHtml(tailored.summary)}</p>`;
  } else {
    summaryEl.innerHTML = "";
  }

  // ── Skills ──
  const skillsEl = $("preview-skills");
  if (tailored.skills_selected && tailored.skills_selected.length > 0) {
    const rows = tailored.skills_selected.map(sg => {
      const tags = (sg.items || []).map(item => {
        return `<span class="skill-tag">${escHtml(item)}</span>`;
      }).join("");
      return `<div class="skill-row">
        <span class="skill-category">${escHtml(sg.category)}:</span>
        <div class="skill-tags">${tags}</div>
      </div>`;
    }).join("");
    skillsEl.innerHTML = `<div class="preview-section-title">Technical Skills</div><div class="skills-grid">${rows}</div>`;
  } else {
    skillsEl.innerHTML = "";
  }

  // ── Projects ──
  const projEl = $("preview-projects");
  let projHtml = "";

  if (tailored.flagship_projects_selected && tailored.flagship_projects_selected.length > 0) {
    const entries = tailored.flagship_projects_selected.map(p => `
      <div class="project-entry">
        <div class="entry-header-row">
          <span class="entry-name">${escHtml(p.name || "")}</span>
          <span class="entry-dates">${escHtml(p.dates || "")}</span>
        </div>
        ${p.tech_stack ? `<div class="entry-sub">Tech: ${escHtml(p.tech_stack)}</div>` : ""}
        ${p.github_link ? `<a class="entry-link" href="${escHtml(p.github_link)}" target="_blank" rel="noopener">GitHub: ${escHtml(p.github_link.replace("https://", "").replace("http://", "").replace(/\/$/, ""))}</a>` : ""}
        ${bulletsHtml(p.bullets)}
      </div>`).join("");
    projHtml += `<div class="preview-section-title">Flagship Projects</div>${entries}`;
  }

  if (tailored.other_projects_selected && tailored.other_projects_selected.length > 0) {
    const entries = tailored.other_projects_selected.map(p => `
      <div class="project-entry">
        <div class="entry-header-row">
          <span class="entry-name">${escHtml(p.name || "")}</span>
          <span class="entry-dates">${escHtml(p.dates || "")}</span>
        </div>
        ${p.tech_stack ? `<div class="entry-sub">Tech: ${escHtml(p.tech_stack)}</div>` : ""}
        ${p.github_link ? `<a class="entry-link" href="${escHtml(p.github_link)}" target="_blank" rel="noopener">GitHub: ${escHtml(p.github_link.replace("https://", "").replace("http://", "").replace(/\/$/, ""))}</a>` : ""}
        ${bulletsHtml(p.bullets)}
      </div>`).join("");
    projHtml += `<div class="preview-section-title">Other Projects</div>${entries}`;
  }

  if (!projHtml && tailored.projects_selected && tailored.projects_selected.length > 0) {
    const entries = tailored.projects_selected.map(p => `
      <div class="project-entry">
        <div class="entry-header-row">
          <span class="entry-name">${escHtml(p.name || "")}</span>
          <span class="entry-dates">${escHtml(p.dates || "")}</span>
        </div>
        ${p.tech_stack ? `<div class="entry-sub">Tech: ${escHtml(p.tech_stack)}</div>` : ""}
        ${p.github_link ? `<a class="entry-link" href="${escHtml(p.github_link)}" target="_blank" rel="noopener">GitHub: ${escHtml(p.github_link.replace("https://", "").replace("http://", "").replace(/\/$/, ""))}</a>` : ""}
        ${bulletsHtml(p.bullets)}
      </div>`).join("");
    projHtml = `<div class="preview-section-title">Projects</div>${entries}`;
  }

  projEl.innerHTML = projHtml;

  // ── Internships ──
  const intEl = $("preview-internships");
  if (tailored.internships_selected && tailored.internships_selected.length > 0) {
    const entries = tailored.internships_selected.map(i => `
      <div class="intern-entry">
        <div class="entry-header-row">
          <span class="entry-name">${escHtml(i.company || "")}</span>
          <span class="entry-dates">${escHtml(i.dates || "")}</span>
        </div>
        <div class="entry-sub">${escHtml(i.role || "")}</div>
        ${bulletsHtml(i.bullets)}
      </div>`).join("");
    intEl.innerHTML = `<div class="preview-section-title">Internship Experience</div>${entries}`;
  } else {
    intEl.innerHTML = "";
  }

  // ── Education ──
  const eduEl = $("preview-education");
  if (tailored.education && tailored.education.length > 0) {
    const entries = tailored.education.map(e => {
      let gpaStr = "";
      if (e.gpa) {
        const degLower = (e.degree || "").toLowerCase();
        const gpaClean = String(e.gpa).replace(/Score:/gi, "").replace(/CGPA:/gi, "").trim();
        const isSchool = degLower.includes("secondary") || degLower.includes("ssc") || degLower.includes("hsc") ||
                         degLower.includes("(x)") || degLower.includes("(xii)") || degLower.includes("xii") ||
                         degLower.includes("10th") || degLower.includes("12th") || degLower.includes("matriculation") ||
                         degLower.includes("higher secondary") || (degLower.split(/\s+/).includes("x"));
        
        if (isSchool) {
          gpaStr = ` — Score: ${gpaClean}${gpaClean.includes("%") ? "" : "%"}`;
        } else {
          gpaStr = ` — CGPA: ${gpaClean}${gpaClean.includes("/") ? "" : "/10.00"}`;
        }
      }
      return `
      <div class="edu-entry">
        <div class="entry-header-row">
          <span class="entry-name">${escHtml(e.institution || "")}</span>
          <span class="entry-dates">${escHtml(e.dates || "")}</span>
        </div>
        <div class="entry-sub">${escHtml(e.degree || "")}${gpaStr}</div>
        ${e.relevant_coursework ? `<div class="entry-sub">Coursework: ${escHtml(e.relevant_coursework)}</div>` : ""}
      </div>`;
    }).join("");
    eduEl.innerHTML = `<div class="preview-section-title">Education</div>${entries}`;
  } else {
    eduEl.innerHTML = "";
  }

  // ── Certifications ──
  const certEl = $("preview-certs");
  if (tailored.certifications && tailored.certifications.length > 0) {
    const entries = tailored.certifications.map(c => `
      <div class="cert-entry">
        <strong>${escHtml(c.name || "")}</strong> — ${escHtml(c.issuer || "")}${c.date ? `, ${escHtml(c.date)}` : ""}
      </div>`).join("");
    certEl.innerHTML = `<div class="preview-section-title">Certifications</div>${entries}`;
  } else {
    certEl.innerHTML = "";
  }
}

// ── Download PDF ──────────────────────────────────────────────
async function downloadPDF() {
  if (!currentPdfFilename) {
    showToast("No PDF available. Please generate a resume first.", "error");
    return;
  }

  const btn = $("download-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">↻</span> Downloading…';

  try {
    const response = await fetch(`/api/download/${encodeURIComponent(currentPdfFilename)}`);
    if (!response.ok) throw new Error("Download failed.");

    const blob = await response.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = currentPdfFilename;
    a.click();
    URL.revokeObjectURL(url);
    showToast("PDF downloaded successfully! ✓", "success");
  } catch (err) {
    showToast(`Download error: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">↓</span> Download PDF';
  }
}

// ── Copy as plain text ────────────────────────────────────────
async function copyPlainText() {
  if (!currentResult) {
    showToast("No resume to copy yet.", "error");
    return;
  }

  const r = currentResult;
  const lines = [];

  // Contact Info
  if (r.contact) {
    const c = r.contact;
    if (c.name) lines.push(c.name.toUpperCase());
    const info = [];
    if (c.email) info.push(c.email);
    if (c.phone) info.push(c.phone);
    if (c.location) info.push(c.location);
    if (info.length > 0) lines.push(info.join("  |  "));
    
    const links = [];
    if (c.linkedin) links.push(`LinkedIn: ${c.linkedin}`);
    if (c.github) links.push(`GitHub: ${c.github}`);
    if (c.portfolio) links.push(`Portfolio: ${c.portfolio}`);
    if (links.length > 0) lines.push(links.join("  |  "));
    
    lines.push("");
  }

  // Summary
  if (r.summary) {
    lines.push("PROFESSIONAL SUMMARY");
    lines.push(r.summary);
    lines.push("");
  }

  // Skills
  if (r.skills_selected && r.skills_selected.length > 0) {
    lines.push("TECHNICAL SKILLS");
    r.skills_selected.forEach(sg => {
      lines.push(`${sg.category}: ${(sg.items || []).join(", ")}`);
    });
    lines.push("");
  }

  // Flagship Projects
  if (r.flagship_projects_selected && r.flagship_projects_selected.length > 0) {
    lines.push("FLAGSHIP PROJECTS");
    r.flagship_projects_selected.forEach(p => {
      lines.push(`${p.name}  |  ${p.dates}`);
      if (p.tech_stack) lines.push(`Tech: ${p.tech_stack}`);
      if (p.github_link) lines.push(`GitHub: ${p.github_link}`);
      (p.bullets || []).forEach(b => lines.push(`• ${b}`));
      lines.push("");
    });
  }

  // Other Projects
  if (r.other_projects_selected && r.other_projects_selected.length > 0) {
    lines.push("OTHER PROJECTS");
    r.other_projects_selected.forEach(p => {
      lines.push(`${p.name}  |  ${p.dates}`);
      if (p.tech_stack) lines.push(`Tech: ${p.tech_stack}`);
      if (p.github_link) lines.push(`GitHub: ${p.github_link}`);
      (p.bullets || []).forEach(b => lines.push(`• ${b}`));
      lines.push("");
    });
  }

  // Projects (General Fallback)
  if (r.projects_selected && r.projects_selected.length > 0) {
    lines.push("PROJECTS");
    r.projects_selected.forEach(p => {
      lines.push(`${p.name}  |  ${p.dates}`);
      if (p.tech_stack) lines.push(`Tech: ${p.tech_stack}`);
      if (p.github_link) lines.push(`GitHub: ${p.github_link}`);
      (p.bullets || []).forEach(b => lines.push(`• ${b}`));
      lines.push("");
    });
  }

  // Internships
  if (r.internships_selected && r.internships_selected.length > 0) {
    lines.push("INTERNSHIP EXPERIENCE");
    r.internships_selected.forEach(i => {
      lines.push(`${i.company}  |  ${i.role}  |  ${i.dates}`);
      (i.bullets || []).forEach(b => lines.push(`• ${b}`));
      lines.push("");
    });
  }

  // Education
  if (r.education && r.education.length > 0) {
    lines.push("EDUCATION");
    r.education.forEach(e => {
      lines.push(`${e.institution}  |  ${e.dates}`);
      lines.push(`${e.degree}${e.gpa ? "  —  GPA: " + e.gpa : ""}`);
      if (e.relevant_coursework) lines.push(`Coursework: ${e.relevant_coursework}`);
      lines.push("");
    });
  }

  // Certifications
  if (r.certifications && r.certifications.length > 0) {
    lines.push("CERTIFICATIONS");
    r.certifications.forEach(c => {
      lines.push(`${c.name} — ${c.issuer}${c.date ? ", " + c.date : ""}`);
    });
  }

  const text = lines.join("\n");

  try {
    await navigator.clipboard.writeText(text);
    showToast("Plain text copied to clipboard! ✓", "success");
    const btn = $("copy-btn");
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="btn-icon">✓</span> Copied!';
    setTimeout(() => { btn.innerHTML = orig; }, 2000);
  } catch {
    // Fallback for browsers that block clipboard API
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity  = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showToast("Copied to clipboard! ✓", "success");
  }
}

// ── Utility: build bullets HTML ───────────────────────────────
function bulletsHtml(bullets) {
  if (!bullets || bullets.length === 0) return "";
  const items = bullets.map(b => `<li>${escHtml(b)}</li>`).join("");
  return `<ul class="bullet-list">${items}</ul>`;
}

// ── Utility: escape HTML ──────────────────────────────────────
function escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Toast notification ────────────────────────────────────────
let _toastTimer = null;

function showToast(message, type = "info") {
  // Remove existing toast if any
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  clearTimeout(_toastTimer);

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  // Trigger animation
  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add("show"));
  });

  _toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}

// ── Allow Ctrl+Enter to submit ────────────────────────────────
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    const btn = $("generate-btn");
    if (btn && !btn.disabled) analyzeKeywords();
  }
});


// ── Trigger File Input Click ─────────────────────────────────
function triggerFileSelect() {
  const fileInput = $("resume-file-input");
  if (fileInput) {
    fileInput.click();
  }
}

// ── File Selection Handler ───────────────────────────────────
function handleFileSelect(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    handleFile(files[0]);
  }
}

// ── File Processing & API upload ─────────────────────────────
async function handleFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (ext !== "pdf" && ext !== "docx") {
    showToast("Unsupported file format. Please upload a PDF or DOCX file.", "error");
    return;
  }

  // Show status inside upload-zone
  const uploadZone = $("upload-zone");
  const origHTML = uploadZone.innerHTML;
  uploadZone.innerHTML = `
    <span class="upload-icon">↻</span>
    <p class="upload-text">Uploading and extracting text...</p>
    <p class="upload-note">Processing ${escHtml(file.name)}</p>
  `;
  uploadZone.style.pointerEvents = "none";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/api/extract-text", {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || `Server error ${response.status}`);
    }

    const data = await response.json();
    masterResumeText = data.extracted_text;

    // Display File Card
    const fileCard = $("file-card");
    $("file-name").textContent = file.name;
    $("file-size").textContent = formatBytes(file.size);
    $("file-icon").textContent = ext === "pdf" ? "📕" : "📘";
    fileCard.classList.remove("hidden");

    // Display Extracted Preview
    $("extracted-text-content").textContent = masterResumeText;
    $("extracted-preview-container").classList.remove("hidden");

    // Hide upload zone
    uploadZone.classList.add("hidden");
    
    showToast("Resume parsed successfully! [OK]", "success");

  } catch (err) {
    showToast(err.message, "error");
    // Restore upload zone
    uploadZone.innerHTML = origHTML;
  } finally {
    uploadZone.style.pointerEvents = "auto";
  }
}

// ── Remove Selected File (full reset) ───────────────────────
function removeSelectedFile() {
  // 1. Clear all resume state
  masterResumeText = null;
  currentResult = null;
  currentPdfFilename = null;
  masterKeywords = [];
  jdKeywords = [];
  keywordAlignments = [];
  selectedMasterKeywords.clear();
  selectedJdKeywords.clear();
  initialMatchFitNote = "";

  // 2. Reset file input and file card
  const fileInput = $("resume-file-input");
  if (fileInput) fileInput.value = "";
  $("file-card").classList.add("hidden");

  // 3. Hide extracted preview, collapse it
  const previewContainer = $("extracted-preview-container");
  if (previewContainer) previewContainer.classList.add("hidden");
  const previewBody = $("extracted-text-body");
  if (previewBody) previewBody.classList.add("collapsed");
  const previewArrow = $("preview-toggle-arrow");
  if (previewArrow) previewArrow.textContent = "▼";
  const previewContent = $("extracted-text-content");
  if (previewContent) previewContent.textContent = "";

  // 4. Restore the upload zone to its original content and show it
  const uploadZone = $("upload-zone");
  if (uploadZone) {
    if (_origUploadZoneHTML) {
      uploadZone.innerHTML = _origUploadZoneHTML;
    }
    uploadZone.style.pointerEvents = "auto";
    uploadZone.classList.remove("hidden");
  }

  // 5. Navigate back to input section (hides keyword/result/loading/error sections)
  showSection("input-section");

  // 6. Re-enable the generate button in case it was disabled
  const genBtn = $("generate-btn");
  if (genBtn) genBtn.disabled = false;

  showToast("Resume removed. Upload a new one to start over.", "info");
}

// ── Toggle Extracted Text Preview ────────────────────────────
function toggleExtractedPreview() {
  const body = $("extracted-text-body");
  const arrow = $("preview-toggle-arrow");
  if (body.classList.contains("collapsed")) {
    body.classList.remove("collapsed");
    arrow.textContent = "▲";
  } else {
    body.classList.add("collapsed");
    arrow.textContent = "▼";
  }
}

// ── Format Bytes Utility ─────────────────────────────────────
function formatBytes(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}


