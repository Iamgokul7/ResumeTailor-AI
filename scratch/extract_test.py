import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import _extract_text_from_file, parse_master_sections, parse_master_edu_entries

def main():
    pdf_path = Path("../test_resume.pdf")
    if not pdf_path.exists():
        pdf_path = Path("S:/RESUME_BUILDER_PROJECT/Resume-Tailor/test_resume.pdf")
    
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()
        
    text = _extract_text_from_file("test_resume.pdf", file_bytes)
    print("--- Extracted Text ---")
    print(text)
    print("----------------------")
    
    sections = parse_master_sections(text)
    print("--- Parsed Sections ---")
    for sec_name, lines in sections.items():
        print(f"Section: {sec_name} ({len(lines)} lines)")
        
    education_lines = sections.get("education", [])
    print("--- Education Lines ---")
    for line in education_lines:
        print(f"  {line}")
        
    edu_entries = parse_master_edu_entries(education_lines)
    print("--- Parsed Education Entries ---")
    for idx, edu in enumerate(edu_entries):
        print(f"  {idx+1}: {edu}")

if __name__ == "__main__":
    main()
