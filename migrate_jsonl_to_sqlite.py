import json
from pathlib import Path
from sqlmodel import Session, SQLModel
from schemas import engine, Prediction
from registry import Registry

def migrate():
    # Create tables
    SQLModel.metadata.create_all(engine)
    
    jsonl_path = Path("data/predictions.jsonl")
    if not jsonl_path.exists():
        print("No predictions.jsonl file found to migrate.")
        return
        
    print(f"Reading predictions from {jsonl_path}...")
    preds = []
    for line in jsonl_path.read_text().splitlines():
        line = line.strip()
        if line:
            p = Prediction.model_validate_json(line)
            preds.append(p)
            
    print(f"Found {len(preds)} predictions. Importing to SQLite...")
    
    reg = Registry()
    added = reg.add_many(preds)
    
    print(f"Successfully migrated {len(added)} predictions to database.")

if __name__ == "__main__":
    migrate()
