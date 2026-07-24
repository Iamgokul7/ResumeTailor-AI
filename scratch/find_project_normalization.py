import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/extracted_project_normalization.txt"

with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line_num, line in enumerate(f, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        content = obj.get("content", "")
        if "flagship_projects_selected" in content and "projects" in content and "replace_file_content" in content:
            out.write(f"Line {line_num} (step {obj.get('step_index')}):\n")
            out.write(content)
            out.write("\n" + "="*80 + "\n")
print("Done!")
