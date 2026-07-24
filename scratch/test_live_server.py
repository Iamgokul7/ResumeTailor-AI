import os
import sys
import json
import pathlib
import pypdf
import requests

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
    
    # Use a requests Session to handle cookies
    session = requests.Session()
    
    print("Logging in to live server http://127.0.0.1:8000/login...")
    login_res = session.post("http://127.0.0.1:8000/login", data={"password": "admin"}, allow_redirects=False)
    print(f"Login Response Code: {login_res.status_code}")
    if login_res.status_code not in (200, 303):
        print("Login failed!")
        return

    print("\nSending HTTP POST to live server /api/generate-resume...")
    payload = {
        "master_resume": master_resume,
        "jd_text": jd_text,
        "selected_keywords": selected_keywords
    }
    
    response = session.post("http://127.0.0.1:8000/api/generate-resume", json=payload)
    print(f"Generate Response Code: {response.status_code}")
    
    if response.status_code != 200:
        print("Error response text:")
        print(response.text)
        return
        
    result = response.json()
    tailored = result["tailored"]
    
    print("\n--- GENERATED PROJECT TITLES & LINKS ---")
    for proj in tailored.get("projects", []):
        print(f"Project Name: '{proj.get('name')}'")
        print(f"  GitHub: '{proj.get('github_link')}'")
        print(f"  Live Demo: '{proj.get('live_demo')}'")
        
    print("\n--- GENERATED TECHNICAL SKILLS ---")
    for cat in tailored.get("skills_selected", []):
        print(f"Category: {cat.get('category')} | Items: {', '.join(cat.get('items', []))}")
        
    print("\n--- UNVERIFIED SKILLS WARNING PAYLOAD ---")
    print(json.dumps(result.get("unverified_skills"), indent=2))
    
    print(f"\nSuccessfully verified HTTP response. PDF filename: {result.get('pdf_filename')}")

if __name__ == "__main__":
    main()
