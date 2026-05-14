import os
import urllib.request
import urllib.parse
try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

def get_broll_image(keyword, out_path):
    if not DDGS:
        return False
    try:
        results = DDGS().images(keyword, max_results=3)
    except Exception as e:
        print(f"B-roll search fail for '{keyword}': {e}")
        return False
    for result in results:
        try:
            url = result.get("image", "")
            if not url:
                continue
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            tmp_path = out_path + ".raw"
            with urllib.request.urlopen(req, timeout=8) as resp, open(tmp_path, "wb") as f:
                f.write(resp.read())
            # Transcode to JPEG via FFmpeg — normalizes PNG/WebP/GIF to a format
            # FFmpeg can reliably use as a looped image input
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path, "-vframes", "1", "-q:v", "2", out_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            os.remove(tmp_path)
            return True
        except Exception:
            if os.path.exists(out_path + ".raw"):
                os.remove(out_path + ".raw")
            continue
    print(f"B-roll fetch failed for '{keyword}' after 3 attempts")
    return False

def get_twemoji(emoji_char, out_path):
    if not emoji_char: return False
    
    try:
        _VARIATION_SELECTORS = {0xFE0E, 0xFE0F}
        codepoint = "-".join([
            hex(ord(c))[2:]
            for c in emoji_char
            if ord(c) > 127 and ord(c) not in _VARIATION_SELECTORS
        ])
        if not codepoint:
            return False
            
        url = f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{codepoint}.png"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp, open(out_path, 'wb') as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"Twemoji fetch fail for '{emoji_char}': {e}")
    return False

def get_sfx(out_path):
    try:
        if not os.path.exists(out_path):
            import subprocess
            # Generate a 0.1s pop sound using ffmpeg
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", 
                "-i", "sine=frequency=600:duration=0.08", 
                "-af", "afade=t=out:st=0.04:d=0.04",
                out_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"SFX generation fail: {e}")
    return False
