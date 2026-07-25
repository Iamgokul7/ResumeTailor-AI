import os
import sys
import json
import pathlib
import pypdf

# Ensure we can import from the workspace root
sys.path.append(str(pathlib.Path(__file__).parent.parent.absolute()))

from gemini_service import generate_tailored_resume
from pdf_service import render_pdf

def main():
    master_resume_path = pathlib.Path("S:/RESUME/Gokul_P_Master_Resume.pdf")
    if not master_resume_path.exists():
        print(f"Error: {master_resume_path} does not exist")
        return
        
    # Extract text from the master resume PDF
    reader = pypdf.PdfReader(master_resume_path)
    lines = []
    for page in reader.pages:
        lines.append(page.extract_text())
    master_resume = "\n".join(lines)
    
    jd_text = """
    Qualcomm is looking for a Systems Test Engineer.
    Responsibilities:
    - Perform system level testing, functional tests, and regression testing on Qualcomm platforms
    - Troubleshooting of system hardware and software issues
    - Write comprehensive test plans and test cases
    - Document defect documentation and track bugs in JIRA
    - Collaborate with developers and present findings (excellent communication skills)
    - Required technologies: Python, C, Linux, Git, scripting, and QA methodologies
    """
    
    selected_keywords = [
        "Python",
        "C",
        "Git",
        "MySQL",
        "Databases",
        "Cloud technologies"
    ]
    
    print("Calling generate_tailored_resume with Qualcomm JD...")
    result = generate_tailored_resume(master_resume, jd_text, selected_keywords)
    
    tailored = result["tailored_resume"]
    
    print("\n--- GENERATED PROJECT TITLES & LINKS ---")
    for proj in tailored.get("projects", []):
        print(f"Project Name: '{proj.get('name')}'")
        print(f"  GitHub: '{proj.get('github_link')}'")
        print(f"  Live Demo: '{proj.get('live_demo')}'")
        
    print("\n--- GENERATED TECHNICAL SKILLS ---")
    for cat in tailored.get("skills_selected", []):
        print(f"Category: {cat.get('category')} | Items: {', '.join(cat.get('items', []))}")
        
    print("\n--- UNVERIFIED SKILLS ---")
    print(json.dumps(result.get("unverified_skills"), indent=2))
    
    print("\nRendering PDF...")
    pdf_path = render_pdf(tailored, tailored.get("contact", {}))
    print(f"PDF generated: {pdf_path}")

if __name__ == "__main__":
    main()
