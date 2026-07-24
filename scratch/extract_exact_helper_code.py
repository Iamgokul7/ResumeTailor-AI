import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"

lines_to_extract = [916, 931, 1136, 1282, 1300, 1489, 1682, 1734, 1818]

extracted_data = {}

with open(transcript_path, "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if line_num in lines_to_extract:
            try:
                obj = json.loads(line)
                extracted_data[line_num] = obj
            except Exception as e:
                print(f"Error parsing line {line_num}: {e}")

# Save to a structured JSON file for inspection
with open("scratch/extracted_steps.json", "w", encoding="utf-8") as out:
    json.dump(extracted_data, out, indent=2)
print("Done!")
