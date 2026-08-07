import os
import json

INPUT_FILE = '/Users/sj.kang/Documents/PYTHON_KSJ/PY_workspace/SKN_WORKSPACE/PROJECT_FINAL/CPC_KPC_CODE.txt'
OUTPUT_FILE = '/Users/sj.kang/Documents/PYTHON_KSJ/PY_workspace/SKN_WORKSPACE/PROJECT_FINAL/CPC_KPC_CODE.json'

def main():
    print(f"Reading input file: {INPUT_FILE}")
    records = []
    
    with open(INPUT_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        header_line = f.readline().strip()
        headers = [h for h in header_line.split('¶') if h]
        print(f"Headers: {headers}")
        
        for line in f:
            line_clean = line.strip('\r\n')
            if not line_clean:
                continue
            parts = line_clean.split('¶')
            
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
    print(f"Writing to JSON: {OUTPUT_FILE}")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out_f:
        json.dump(records, out_f, ensure_ascii=False, indent=2)

    print("JSON file created successfully!")

if __name__ == '__main__':
    main()
