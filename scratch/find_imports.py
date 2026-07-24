with open("test_pipeline.py", "r", encoding="utf-8") as f:
    for line_num, line in enumerate(f, 1):
        if "gemini_service" in line or "validate_tailored_resume" in line or "generate_tailored_resume" in line or "deduplicate" in line:
            print(f"Line {line_num}: {line.strip()}")
