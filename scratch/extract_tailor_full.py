import subprocess

cmd = "git show 202e896:gemini_service.py"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
lines = res.stdout.splitlines()

with open("scratch/original_tailor.txt", "w", encoding="utf-8") as out:
    found = False
    for idx, line in enumerate(lines, 1):
        if "def tailor_resume" in line:
            found = True
        if found:
            out.write(f"{idx}: {line}\n")
            if idx > 360:
                break
print("Done!")
