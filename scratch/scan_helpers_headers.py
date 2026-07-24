with open("scratch/extracted_all_helpers.txt", "r", encoding="utf-8") as f:
    for line in f:
        if line.startswith("Line ") and "Helper" in line:
            print(line.strip())
