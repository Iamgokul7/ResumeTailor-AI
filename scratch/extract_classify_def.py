import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_classify_def.txt"

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line_num, line in enumerate(f, 1):
        if line_num == 1682:
            obj = json.loads(line)
            out.write(json.dumps(obj, indent=2))
print("Done!")
