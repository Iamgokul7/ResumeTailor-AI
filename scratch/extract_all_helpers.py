import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_all_helpers.txt"

helpers = [
    "def restore_project_links",
    "def find_full_project_title_from_blob",
    "def clean_master_project_line",
    "def get_buzzword_suggestions",
    "def deterministic_buzzword_cleanup",
    "def filter_non_skills_via_classification",
    "def classify_skills_with_llm"
]

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line_num, line in enumerate(f, 1):
        for helper in helpers:
            if helper in line:
                out.write(f"Line {line_num} | Helper {helper}:\n")
                out.write(line)
                out.write("\n------------------\n")
                break
print("Done extracting helpers!")
