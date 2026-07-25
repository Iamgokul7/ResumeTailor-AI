import json
import os

with open("scratch/extracted_steps.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for line_num_str, obj in data.items():
    t_type = obj.get("type")
    content = obj.get("content", "")
    
    output_filename = f"scratch/step_{line_num_str}_{t_type}.txt"
    with open(output_filename, "w", encoding="utf-8") as out:
        out.write(f"=== LINE {line_num_str} | TYPE {t_type} ===\n")
        
        # If it contains tool calls, let's extract their args
        tool_calls = obj.get("tool_calls", [])
        if tool_calls:
            out.write("TOOL CALLS:\n")
            for idx, tc in enumerate(tool_calls):
                out.write(f"Tool {idx}: {tc.get('name')}\n")
                args = tc.get("args", {})
                out.write(json.dumps(args, indent=2))
                out.write("\n")
        else:
            out.write("CONTENT:\n")
            out.write(content)
            
    print(f"Wrote {output_filename}")
