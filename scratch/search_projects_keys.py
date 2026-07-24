import subprocess

cmd = "git show 202e896:gemini_service.py"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
lines = res.stdout.splitlines()

for idx, line in enumerate(lines, 1):
    if '"projects"' in line or '"section_order"' in line or '"section_titles"' in line:
        print(f"Line {idx}: {line.strip()}")
