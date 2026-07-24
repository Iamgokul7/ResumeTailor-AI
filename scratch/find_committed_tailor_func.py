import subprocess

cmd = "git show 202e896:gemini_service.py"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
lines = res.stdout.splitlines()

found = False
for idx, line in enumerate(lines, 1):
    if "def tailor_resume" in line:
        found = True
        print(f"Found on line {idx}")
    if found and idx < 950: # view lines after it
        print(f"{idx}: {line}")
