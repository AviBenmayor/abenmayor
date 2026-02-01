import pandas as pd
import os

class FidelityClient:
    def __init__(self, csv_path: str = None):
        self.csv_path = csv_path

    def load_positions(self, file_path: str = None):
        """
        Expects a standard Fidelity CSV export.
        Columns often include: 'Symbol', 'Description', 'Quantity', 'Last Price', 'Current Value'
        """
        path = file_path or self.csv_path
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"Fidelity CSV not found at {path}")
            
        try:
            # Fidelity CSVs sometimes have metadata at the top/bottom, might need skiprows
            # Assuming a clean CSV or one with headers on the first line for now
            df = pd.read_csv(path)
            
            # Basic validation/normalization
            required_cols = ['Symbol', 'Quantity', 'Current Value']
            # Check if columns exist (case insensitive) .columns are usually capitalized
            # But let's just return the raw list of dicts for now
            return df.to_dict(orient='records')
        except Exception as e:
            print(f"Error parsing Fidelity CSV: {e}")
            return []
