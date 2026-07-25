with open("static/app.js", "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if "flagship" in line or "other_projects" in line or "projects_selected" in line:
            print(f"Line {line_num}: {line.strip()}")
