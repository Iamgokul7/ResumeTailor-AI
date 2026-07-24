import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_views.txt"

steps_to_extract = [975, 981, 983, 985, 987, 989, 991, 1009]

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line in f:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
            
        step = obj.get("step_index", 0)
        if step in steps_to_extract:
            out.write(f"\n========================================\nSTEP {step} VIEW\n========================================")
            out.write(obj.get("content", ""))
            out.write("\n")
print("Done extracting!")
