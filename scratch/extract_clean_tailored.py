import subprocess

cmd = "git show 202e896:gemini_service.py"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
lines = res.stdout.splitlines()

found = False
for idx, line in enumerate(lines, 1):
    if "def clean_tailored_resume" in line:
        found = True
    if found:
        print(line)
        if idx > 690:  # print a chunk of lines
            break
