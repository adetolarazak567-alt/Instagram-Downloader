import requests
import random
import string
import sqlite3
import time
import re
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

session = requests.Session()

# Proper browser headers to avoid bot detection
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

# ==========================
# METHOD 1: YT-DLP (MOST RELIABLE)
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
            },
            "cookiesfrombrowser": None,  # No browser cookies needed for public posts
            "ignoreerrors": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        # Get direct video URL
        video_url = info.get("url")
        if not video_url and "formats" in info:
            # Find best mp4 format
            for f in reversed(info.get("formats", [])):
                if f.get("ext") == "mp4" and f.get("url"):
                    video_url = f["url"]
                    break
            # Fallback to any format with URL
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
# METHOD 2: EMBEDDED JSON SCRAPE (FALLBACK)
# ==========================

def fetch_embedded_json(url):
    """Scrape Instagram page for embedded JSON data"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.instagram.com/",
        }

        r = session.get(url, headers=headers, timeout=10, allow_redirects=True)

        if r.status_code != 200:
            return None

        # Look for sharedData or additional data in script tags
        patterns = [
            r'<script type="text/javascript">window\._sharedData = (.*?);</script>',
            r'<script type="application/json" data-sjs>(.*?)</script>',
            r'"video_url":"(https://[^"]+)"',
            r'"contentUrl":"(https://[^"]+)"',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, r.text)
            for match in matches:
                if "http" in match:
                    # Try to parse JSON or extract URL
                    try:
                        data = json.loads(match)
                        if isinstance(data, dict):
                            # Navigate through possible structures
                            video_url = (
                                data.get("entry_data", {})
                                .get("PostPage", [{}])[0]
                                .get("graphql", {})
                                .get("shortcode_media", {})
                                .get("video_url")
                            )
                            if video_url:
                                return {"video_url": video_url, "title": "Instagram Video", "thumbnail": "", "uploader": ""}
                    except:
                        # Direct URL match
                        if match.startswith("http") and (".mp4" in match or "instagram.com" in match):
                            return {"video_url": match, "title": "Instagram Video", "thumbnail": "", "uploader": ""}

        # Try og:video meta tag
        soup = BeautifulSoup(r.text, "html.parser")
        og_video = soup.find("meta", property="og:video")
        if og_video and og_video.get("content"):
            return {
                "video_url": og_video["content"],
                "title": "Instagram Video",
                "thumbnail": "",
                "uploader": ""
            }

        # Try all meta tags for video URLs
        for meta in soup.find_all("meta"):
            content = meta.get("content", "")
            if content and content.startswith("http") and (".mp4" in content or "cdninstagram" in content):
                return {
                    "video_url": content,
                    "title": "Instagram Video",
                    "thumbnail": "",
                    "uploader": ""
                }

    except Exception as e:
        print("HTML scrape error:", e)

    return None


# ==========================
# METHOD 3: GRAPHQL API (LAST RESORT)
# ==========================

def fetch_graphql(url):
    """Try to extract shortcode and query GraphQL"""
    try:
        # Extract shortcode from URL
        match = re.search(r'instagram\.com/(?:p|reel|tv)/([^/?]+)', url)
        if not match:
            return None

        shortcode = match.group(1)

        # Instagram's public GraphQL endpoint (requires no auth for public posts sometimes)
        graphql_url = "https://www.instagram.com/api/v1/media/shortcode/{}/".format(shortcode)

        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",  # Instagram web app ID
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
        }

        r = session.get(graphql_url, headers=headers, timeout=10)

        if r.status_code == 200:
            data = r.json()
            video_url = (
                data.get("items", [{}])[0]
                .get("video_versions", [{}])[0]
                .get("url")
            )
            if video_url:
                return {
                    "video_url": video_url,
                    "title": data.get("items", [{}])[0].get("caption", {}).get("text", "Instagram Video")[:100],
                    "thumbnail": "",
                    "uploader": data.get("items", [{}])[0].get("user", {}).get("username", ""),
                }

    except Exception as e:
        print("GraphQL error:", e)

    return None


# ==========================
# FETCH CONTROLLER
# ==========================

def get_video(url):
    # Check cache first
    if url in cache:
        return cache[url]

    # Try methods in order of reliability
    result = fetch_ytdlp(url)

    if not result:
        result = fetch_embedded_json(url)

    if not result:
        result = fetch_graphql(url)

    if result and result.get("video_url"):
        cache[url] = result
        return result

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

    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    result = get_video(url)

    if not result or not result.get("video_url"):
        return jsonify({"success": False, "message": "Failed to fetch video. Instagram may have blocked this content or it requires login."}), 500

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
    import json  # needed for embedded JSON parsing
    app.run(host="0.0.0.0", port=5000)
