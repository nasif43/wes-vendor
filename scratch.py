import os
import re

for root, dirs, files in os.walk("app/templates"):
    for file in files:
        if file.endswith(".html"):
            path = os.path.join(root, file)
            with open(path, "r") as f:
                content = f.read()
            
            # Find lines with 'vendor' (case insensitive)
            lines = content.split('\n')
            for i, line in enumerate(lines):
                # heuristic: if it has 'vendor' but not in common code contexts
                if re.search(r'\bvendor\b', line, re.IGNORECASE):
                    # ignore common code patterns
                    if re.search(r'(href="/vendors|vendor\.|vendor_|vendor-|{%\s*for\s+vendor|\bvendors\b|\bvendor\b.*=)', line, re.IGNORECASE):
                        # But wait, what if it's "Add Vendor"? That has \bVendor\b.
                        # Let's just print the line and we will visually inspect.
                        pass
                    print(f"{path}:{i+1}: {line.strip()}")
