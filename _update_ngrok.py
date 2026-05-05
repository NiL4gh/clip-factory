import json

with open('colab_launcher.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

# The launch cell is usually index 3
for cell in nb['cells']:
    if 'source' in cell and len(cell['source']) > 0 and 'CELL 2' in cell['source'][0]:
        new_source = []
        for line in cell['source']:
            if "ngrok_token = input('Paste your ngrok auth token: ')" in line:
                new_source.append("            ngrok_token = '3DHR9cBJA1DwgIYWqm28CFKjkQT_3E1sWDqq5LvfsSYdQzkUm'\n")
            elif "ngrok.set_auth_token(ngrok_token.strip())" in line:
                new_source.append("            ngrok.set_auth_token(ngrok_token)\n")
            else:
                new_source.append(line)
        cell['source'] = new_source

with open('colab_launcher.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1)

print("Updated ngrok token in colab_launcher.ipynb")
