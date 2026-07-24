import glob

for filepath in glob.glob("**/*", recursive=True):
    if not filepath.endswith((".py", ".js", ".html")):
        continue
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            if "flagship_projects_selected" in content or "other_projects_selected" in content:
                print(f"Found in {filepath}")
    except Exception:
        continue
