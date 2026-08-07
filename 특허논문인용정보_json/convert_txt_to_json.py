import os
import json
import math

INPUT_FILE = '/Users/sj.kang/Documents/PYTHON_KSJ/PY_workspace/SKN_WORKSPACE/PROJECT_FINAL/PatentLiteratureCitationData_245310.txt'
OUTPUT_DIR = '/Users/sj.kang/Documents/PYTHON_KSJ/PY_workspace/SKN_WORKSPACE/PROJECT_FINAL'
NUM_PARTS = 5

def main():
    print(f"Reading input file: {INPUT_FILE}")
    records = []
    
    with open(INPUT_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        header_line = f.readline().strip()
        headers = [h for h in header_line.split('<¶>') if h]
        print(f"Headers: {headers}")
        
        for line in f:
            line_clean = line.strip('\r\n')
            if not line_clean:
                continue
            parts = line_clean.split('<¶>')
            if parts[-1] == '':
                parts = parts[:-1]
            
            row = {}
            for h, v in zip(headers, parts):
                v_str = v.strip()
                if v_str == 'null' or v_str == '':
                    row[h] = None
                else:
                    row[h] = v_str
            records.append(row)

    total_records = len(records)
    print(f"Total records loaded: {total_records}")

    chunk_size = math.ceil(total_records / NUM_PARTS)
    print(f"Chunk size: ~{chunk_size} records per file")

    for part_idx in range(NUM_PARTS):
        start_idx = part_idx * chunk_size
        end_idx = min((part_idx + 1) * chunk_size, total_records)
        part_records = records[start_idx:end_idx]
        
        output_filename = os.path.join(OUTPUT_DIR, f"PatentLiteratureCitationData_part{part_idx + 1}.json")
        print(f"Writing part {part_idx + 1} ({len(part_records)} records) -> {output_filename}")
        
        with open(output_filename, 'w', encoding='utf-8') as out_f:
            json.dump(part_records, out_f, ensure_ascii=False, indent=2)

    print("All JSON files created successfully!")

if __name__ == '__main__':
    main()
