import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_check_keyword_def.txt"

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line in f:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
            
        step = obj.get("step_index", 0)
        content = obj.get("content", "")
        if "def check_keyword_present_in_elements" in content and "VIEW_FILE" in obj.get("type", ""):
            out.write(f"Step {step} viewed check_keyword_present_in_elements\n")
            out.write(content)
            out.write("\n------------------\n")
print("Done extracting check_keyword def!")
