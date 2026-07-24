import json
import os

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"

with open(transcript_path, "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
            
        step = obj.get("step_index", 0)
        # We only care about steps before this turn started (step 1038)
        if step >= 1038:
            continue
            
        t_type = obj.get("type")
        if t_type == "VIEW_FILE" and "gemini_service.py" in obj.get("content", ""):
            # Let's see what was viewed
            content = obj.get("content", "")
            lines = content.splitlines()
            first_few = [l for l in lines if "File Path:" in l or "Total Lines:" in l or "Showing lines" in l]
            print(f"Line {line_num} | Step {step} | VIEW_FILE: {first_few}")
        elif t_type == "CODE_ACTION" and "gemini_service.py" in obj.get("content", ""):
            print(f"Line {line_num} | Step {step} | CODE_ACTION: {obj.get('content')[:150]}...")
