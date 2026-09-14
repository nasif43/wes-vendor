import os
import re

def replace_ui_text(content):
    # Split by script tags, html tags, and jinja tags
    # regex to match:
    # 1. <script>...</script>
    # 2. <...> (HTML tags)
    # 3. {{ ... }} (Jinja variables)
    # 4. {% ... %} (Jinja blocks)
    # 5. {# ... #} (Jinja comments)
    pattern = re.compile(r'(<script\b[^>]*>.*?</script>|<[^>]+>|\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})', re.IGNORECASE | re.DOTALL)
    
    parts = pattern.split(content)
    
    for i, part in enumerate(parts):
        if not part:
            continue
            
        is_protected = False
        if part.startswith('<script'): is_protected = True
        elif part.startswith('<'):
            # It's an HTML tag. We only want to replace specific attributes like placeholder, title, value (for buttons)
            new_part = part
            new_part = re.sub(r'(placeholder="[^"]*)Vendors([^"]*")', r'\1Suppliers\2', new_part)
            new_part = re.sub(r'(placeholder="[^"]*)vendors([^"]*")', r'\1suppliers\2', new_part)
            new_part = re.sub(r'(placeholder="[^"]*)Vendor([^"]*")', r'\1Supplier\2', new_part)
            new_part = re.sub(r'(placeholder="[^"]*)vendor([^"]*")', r'\1supplier\2', new_part)

            new_part = re.sub(r'(title="[^"]*)Vendors([^"]*")', r'\1Suppliers\2', new_part)
            new_part = re.sub(r'(title="[^"]*)vendors([^"]*")', r'\1suppliers\2', new_part)
            new_part = re.sub(r'(title="[^"]*)Vendor([^"]*")', r'\1Supplier\2', new_part)
            new_part = re.sub(r'(title="[^"]*)vendor([^"]*")', r'\1supplier\2', new_part)
            
            if 'type="submit"' in new_part or 'type="button"' in new_part:
                new_part = re.sub(r'(value="[^"]*)Vendor([^"]*")', r'\1Supplier\2', new_part)
                new_part = re.sub(r'(value="[^"]*)vendor([^"]*")', r'\1supplier\2', new_part)
                new_part = re.sub(r'(value="[^"]*)Vendors([^"]*")', r'\1Suppliers\2', new_part)
                new_part = re.sub(r'(value="[^"]*)vendors([^"]*")', r'\1suppliers\2', new_part)
            
            parts[i] = new_part
            is_protected = True
        elif part.startswith('{{') or part.startswith('{%') or part.startswith('{#'):
            is_protected = True
            
        if not is_protected:
            # It's a text node. Replace Words.
            # Use regex to match whole words to avoid messing up inside words, though vendor -> supplier is safe
            p = part
            p = p.replace('Vendors', 'Suppliers')
            p = p.replace('vendors', 'suppliers')
            p = p.replace('Vendor', 'Supplier')
            p = p.replace('vendor', 'supplier')
            
            # Special case for Vendor(s) -> Supplier(s) handled inherently since we replace 'Vendor' then leave '(s)'
            parts[i] = p

    return "".join(parts)

for root, dirs, files in os.walk("app/templates"):
    for file in files:
        if file.endswith(".html"):
            path = os.path.join(root, file)
            with open(path, "r") as f:
                content = f.read()
            
            new_content = replace_ui_text(content)
            
            if new_content != content:
                with open(path, "w") as f:
                    f.write(new_content)
                print(f"Updated {path}")
