import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_check_keyword_wide.txt"

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line_num, line in enumerate(f, 1):
        if "check_keyword_present_in_elements" in line:
            out.write(f"Line {line_num} contains the keyword\n")
            out.write(line)
            out.write("\n------------------\n")
print("Done wide search!")
