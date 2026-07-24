import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_step_1203.txt"

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line in f:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
            
        step = obj.get("step_index", 0)
        if step in (1202, 1203):
            out.write(f"Step {step}:\n")
            out.write(json.dumps(obj, indent=2))
            out.write("\n------------------\n")
print("Done extracting step 1203!")
