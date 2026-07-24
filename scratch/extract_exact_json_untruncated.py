import json

transcript_path = r"C:\Users\iamgo\.gemini\antigravity-ide\brain\c6653bea-d8c3-43f6-946d-085d069d41d7\.system_generated\logs\transcript_full.jsonl"
output_path = r"scratch/step_1061_content.txt"

# Step 1061 is inside line 1682 of transcript_full.jsonl (since line 1682 was step 1317 which ran a command to print it)
# Wait! Let's just find the step 1061 directly in the transcript file!
with open(transcript_path, "r", encoding="utf-8") as f, open(output_path, "w", encoding="utf-8") as out:
    for line_num, line in enumerate(f, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
            
        step = obj.get("step_index", 0)
        if step == 1061:
            out.write(f"Step {step} content:\n")
            out.write(obj.get("content", ""))
            out.write("\n")
            # If tool_calls exist, let's also dump them
            tc = obj.get("tool_calls", [])
            if tc:
                out.write("TOOL CALLS:\n")
                out.write(json.dumps(tc, indent=2))
            break
print("Done extracting step 1061 untruncated!")
