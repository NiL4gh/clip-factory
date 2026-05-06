import json

with open("colab_launcher.ipynb", "r", encoding="utf-8") as f:
    data = json.load(f)

source = data['cells'][2]['source']
for i, line in enumerate(source):
    if line.startswith("!pip install pyngrok"):
        source.insert(i + 1, "!CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python --quiet --upgrade --no-cache-dir\n")
        break

with open("colab_launcher.ipynb", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=1)
