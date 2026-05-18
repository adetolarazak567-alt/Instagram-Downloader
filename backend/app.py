import requests
import random
import string
import sqlite3
import time
import re
import json
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
from bs4 import BeautifulSoup
import concurrent.futures

app = Flask(__name__)
CORS(app)

session = requests.Session()

# Proper browser headers to avoid blocks
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

# ==========================
# SQLITE DATABASE
# ==========================

conn = sqlite3.connect("insta_stats.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS stats(
key TEXT PRIMARY KEY,
value INTEGER
)
""")

for k in ["requests","downloads","cache_hits","videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats VALUES (?,?)",(k,0))

conn.commit()

# ==========================
# CACHE
# ==========================

cache = {}

# ==========================
# UTIL
# ==========================

def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters+string.digits,k=length))

def clean_filename(text):
    if not text:
        text = "ToolifyX Downloader"
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text[:120]

def extract_shortcode(url):
    """Extract Instagram shortcode from various URL formats"""
    patterns = [
        r'instagram\.com/p/([^/?]+)',
        r'instagram\.com/reel/([^/?]+)',
        r'instagram\.com/tv/([^/?]+)',
        r'instagram\.com/reels/([^/?]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# ==========================
# METHOD 1: YT-DLP (BEST EFFORT)
# ==========================

def fetch_ytdlp(url):
    try:
        ydl_opts = {
            "quiet": True,
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 3,
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://www.instagram.com/",
            },
            "cookiesfrombrowser": None,
            "ignoreerrors": True,
            "no_warnings": True,
            "extractor_retries": 3,
            "fragment_retries": 3,
            "skip_unavailable_fragments": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        # Get direct video URL
        video_url = info.get("url")
        if not video_url and "formats" in info:
            for f in reversed(info.get("formats", [])):
                if f.get("ext") == "mp4" and f.get("url"):
                    video_url = f["url"]
                    break
            if not video_url:
                for f in reversed(info.get("formats", [])):
                    if f.get("url"):
                        video_url = f["url"]
                        break

        if video_url:
            return {
                "video_url": video_url,
                "title": info.get("title", "Instagram Video"),
                "thumbnail": info.get("thumbnail", ""),
                "uploader": info.get("uploader", ""),
            }

    except Exception as e:
        print("yt-dlp error:", e)

    return None


# ==========================
# METHOD 2: INSTAGRAM DOWNLOADER API (savefrom.net style)
# ==========================

def fetch_savefrom(url):
    """Try savefrom.net API"""
    try:
        api_url = "https://savefrom.net/api/convert"
        res = session.post(
            api_url,
            data={"url": url},
            timeout=15,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://savefrom.net",
                "Referer": "https://savefrom.net/",
            }
        )
        if res.status_code == 200:
            data = res.json()
            video_url = data.get("url") or data.get("download_url")
            if video_url:
                return {
                    "video_url": video_url,
                    "title": data.get("meta", {}).get("title", "Instagram Video"),
                    "thumbnail": data.get("thumb", ""),
                    "uploader": "",
                }
    except Exception as e:
        print("savefrom error:", e)
    return None


# ==========================
# METHOD 3: SNAPINSTA / DDOWNR STYLE API
# ==========================

def fetch_snapinsta(url):
    """Try snapinsta.app API pattern"""
    try:
        # First get token
        res = session.get("https://snapinsta.app/", timeout=10)
        if res.status_code != 200:
            return None

        # Extract any token if needed
        token_match = re.search(r'name="_token" value="([^"]+)"', res.text)
        token = token_match.group(1) if token_match else ""

        res = session.post(
            "https://snapinsta.app/action.php",
            data={"url": url, "token": token, "action": "post"},
            timeout=15,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://snapinsta.app",
                "Referer": "https://snapinsta.app/",
            }
        )

        if res.status_code == 200:
            # Response is usually HTML with download links
            soup = BeautifulSoup(res.text, "html.parser")
            video_tag = soup.find("a", {"download": True})
            if video_tag and video_tag.get("href"):
                return {
                    "video_url": video_tag["href"],
                    "title": "Instagram Video",
                    "thumbnail": "",
                    "uploader": "",
                }

            # Try to find any video URL in the response
            video_match = re.search(r'href="(https://[^"]+\.mp4[^"]*)"', res.text)
            if video_match:
                return {
                    "video_url": video_match.group(1),
                    "title": "Instagram Video",
                    "thumbnail": "",
                    "uploader": "",
                }

    except Exception as e:
        print("snapinsta error:", e)
    return None


# ==========================
# METHOD 4: INFLACT / TOOLZU PATTERN
# ==========================

def fetch_inflact(url):
    """Try inflact-style API"""
    try:
        shortcode = extract_shortcode(url)
        if not shortcode:
            return None

        res = session.post(
            "https://api.inflact.com/v2/media",
            json={"url": url, "shortcode": shortcode},
            timeout=15,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://inflact.com",
                "Referer": "https://inflact.com/",
            }
        )

        if res.status_code == 200:
            data = res.json()
            video_url = data.get("video_url") or data.get("url")
            if video_url:
                return {
                    "video_url": video_url,
                    "title": data.get("title", "Instagram Video"),
                    "thumbnail": data.get("thumbnail", ""),
                    "uploader": data.get("username", ""),
                }

    except Exception as e:
        print("inflact error:", e)
    return None


# ==========================
# METHOD 5: DDINSTA / IGRAM PATTERN
# ==========================

def fetch_ddinsta(url):
    """Try ddinsta.com or similar pattern"""
    try:
        res = session.post(
            "https://www.ddinstagram.com/reels/",
            data={"url": url},
            timeout=15,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.ddinstagram.com",
                "Referer": "https://www.ddinstagram.com/",
            }
        )

        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            video = soup.find("video")
            if video and video.get("src"):
                return {
                    "video_url": video["src"],
                    "title": "Instagram Video",
                    "thumbnail": "",
                    "uploader": "",
                }

            # Try download links
            for a in soup.find_all("a", href=True):
                if "download" in a.get("class", []) or ".mp4" in a["href"]:
                    return {
                        "video_url": a["href"],
                        "title": "Instagram Video",
                        "thumbnail": "",
                        "uploader": "",
                    }

    except Exception as e:
        print("ddinsta error:", e)
    return None


# ==========================
# METHOD 6: RAPIDAPI INSTAGRAM DOWNLOADER
# ==========================

def fetch_rapidapi(url):
    """RapidAPI Instagram downloader (requires API key)"""
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        return None

    try:
        res = session.get(
            "https://instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com/get-info-rapid/",
            params={"url": url},
            timeout=15,
            headers={
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": "instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com",
            }
        )
        if res.status_code == 200:
            data = res.json()
            video_url = data.get("video_url") or data.get("download_url")
            if video_url:
                return {
                    "video_url": video_url,
                    "title": data.get("title", "Instagram Video"),
                    "thumbnail": data.get("thumbnail", ""),
                    "uploader": data.get("username", ""),
                }

    except Exception as e:
        print("rapidapi error:", e)
    return None


# ==========================
# FETCH CONTROLLER (PARALLEL)
# ==========================

def get_video(url):
    # Check cache first
    if url in cache:
        return cache[url]

    # Run all methods in parallel, return first success
    methods = [
        fetch_ytdlp,
        fetch_savefrom,
        fetch_snapinsta,
        fetch_inflact,
        fetch_ddinsta,
        fetch_rapidapi,
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(method, url): method.__name__ for method in methods}

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result and result.get("video_url"):
                    cache[url] = result
                    return result
            except Exception as e:
                print(f"Method {futures[future]} failed: {e}")

    return None


# ==========================
# FETCH API
# ==========================

@app.route("/api/fetch", methods=["POST"])
def fetch():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    # Basic validation
    if "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    result = get_video(url)

    if not result or not result.get("video_url"):
        return jsonify({
            "success": False,
            "message": "Failed to fetch video. Instagram may require login, or the post is private/deleted. Try a public post."
        }), 500

    c.execute("UPDATE stats SET value=value+1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value=value+1 WHERE key='videos_served'")
    conn.commit()

    return jsonify({
        "success": True,
        "videoUrl": result["video_url"],
        "title": result.get("title", "Instagram Video"),
        "thumbnail": result.get("thumbnail", ""),
        "uploader": result.get("uploader", ""),
    })


# ==========================
# DOWNLOAD (RESUMABLE)
# ==========================

@app.route("/api/download")
def download():
    video_url = request.args.get("url")
    mode = request.args.get("mode", "download")
    custom_filename = request.args.get("filename", "")

    if not video_url:
        return jsonify({"success": False, "message": "No video URL"}), 400

    try:
        # Parse Range header from client
        range_header = request.headers.get("Range")

        # Build headers for source request
        source_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "video/webm,video/mp4,video/*,*/*;q=0.9",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.instagram.com/",
        }
        if range_header:
            source_headers["Range"] = range_header

        # Request from source with range support
        r = session.get(video_url, stream=True, timeout=30, headers=source_headers)

        # Build filename
        if custom_filename:
            filename = clean_filename(custom_filename)
            if not filename.endswith(".mp4"):
                filename += ".mp4"
        else:
            rand = random_string()
            filename = f"ToolifyX-{rand}.mp4"

        # Determine status code
        status_code = 206 if r.status_code == 206 else 200

        # Build response headers
        headers = {
            "Content-Type": r.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",  # Tell client we support resume
        }

        # Forward range-related headers
        if "Content-Range" in r.headers:
            headers["Content-Range"] = r.headers["Content-Range"]
        if "Content-Length" in r.headers:
            headers["Content-Length"] = r.headers["Content-Length"]

        # Content-Disposition
        if mode == "preview":
            headers["Content-Disposition"] = f'inline; filename="{filename}"'
        else:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        # Stream generator with larger chunks
        def generate():
            for chunk in r.iter_content(chunk_size=262144):  # 256KB chunks
                if chunk:
                    yield chunk

        return Response(
            generate(),
            status=status_code,
            headers=headers
        )

    except Exception as e:
        print("Download error:", e)
        return jsonify({"success": False, "message": str(e)}), 500


# ==========================
# HOME
# ==========================

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "service": "Instagram Downloader API",
        "version": "2.0"
    })


# ==========================
# START
# ==========================

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=5000)
