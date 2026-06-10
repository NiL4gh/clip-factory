import re

with open('frontend/src/app/page.tsx', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix renderClip
text = text.replace('    try {\n      const settings = getSettings(index);', '    let ws: WebSocket | null = null;\n    try {\n      const settings = getSettings(index);')
text = text.replace('      const ws = new WebSocket(wsUrl());\n      ws.onmessage = handleWsMessage;\n\n      const taskId = res.data.task_id;', '      ws = new WebSocket(wsUrl());\n      ws.onmessage = handleWsMessage;\n\n      const taskId = res.data.task_id;')

# Fix renderAllClips
text = text.replace('    try {\n      await axios.post(`${API_BASE}/render_all`, {', '    let ws: WebSocket | null = null;\n    try {\n      await axios.post(`${API_BASE}/render_all`, {')
text = text.replace('      const ws = new WebSocket(wsUrl());\n      ws.onmessage = handleWsMessage;\n      \n      const poll = setInterval(', '      ws = new WebSocket(wsUrl());\n      ws.onmessage = handleWsMessage;\n      \n      const poll = setInterval(')

# Change all remaining ws.close() to ws?.close()
# Since we might have ws.close() inside setTimer interval success states which is fine but ws?.close() is safer
text = text.replace('ws.close();', 'ws?.close();')

with open('frontend/src/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done fixing ws scopes")
