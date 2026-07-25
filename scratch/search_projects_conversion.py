import re

with open("gemini_service.py", "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if "flagship" in line or "other_projects" in line:
            print(f"Line {line_num}: {line.strip()}")
