import os
import requests
import random
import string
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

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

# ==========================
# CACHE
# ==========================

cache = {}

# ==========================
# UTIL
# ==========================

def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def clean_filename(text):
    if not text:
        text = "Instagram Video"
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text[:120]

def extract_shortcode(url):
    patterns = [
        r'instagram\.com/p/([^/?]+)',
        r'instagram\.com/reel/([^/?]+)',
        r'instagram\.com/reels/([^/?]+)',
        r'instagram\.com/tv/([^/?]+),
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# ==========================
# METHOD 1: YT-DLP (PRIMARY)
# ==========================

def fetch_ytdlp(url):
    try:
        ydl_opts = {
            "quiet": True,
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 2,
            "nocheckcertificate": True,
            "no_warnings": True,
            "extractor_retries": 2,
            "fragment_retries": 2,
            "skip_unavailable_fragments": True,
            "cookiesfrombrowser": None,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://www.instagram.com/",
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        video_url = info.get("url")
        if not video_url and "formats" in info:
            formats = info.get("formats", [])
            for f in reversed(formats):
                if f.get("ext") == "mp4" and f.get("url"):
                    video_url = f["url"]
                    break
            if not video_url:
                for f in reversed(formats):
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
# METHOD 2: RAPIDAPI (REQUIRES KEY)
# ==========================

def fetch_rapidapi(url):
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
# FETCH CONTROLLER
# ==========================

def get_video(url):
    if url in cache:
        return cache[url]

    methods = [fetch_ytdlp, fetch_rapidapi]

    for method in methods:
        try:
            result = method(url)
            if result and result.get("video_url"):
                cache[url] = result
                return result
        except Exception as e:
            print(f"Method {method.__name__} failed: {e}")

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

    if "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    result = get_video(url)

    if not result or not result.get("video_url"):
        return jsonify({
            "success": False,
            "message": "Failed to fetch video. The post may be private, deleted, or require login. Public posts only."
        }), 500

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
        range_header = request.headers.get("Range")

        source_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "video/webm,video/mp4,video/*,*/*;q=0.9",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.instagram.com/",
        }
        if range_header:
            source_headers["Range"] = range_header

        r = session.get(video_url, stream=True, timeout=30, headers=source_headers)

        if custom_filename:
            filename = clean_filename(custom_filename)
            if not filename.endswith(".mp4"):
                filename += ".mp4"
        else:
            rand = random_string()
            filename = f"IG-{rand}.mp4"

        status_code = 206 if r.status_code == 206 else 200

        headers = {
            "Content-Type": r.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",
        }

        if "Content-Range" in r.headers:
            headers["Content-Range"] = r.headers["Content-Range"]
        if "Content-Length" in r.headers:
            headers["Content-Length"] = r.headers["Content-Length"]

        if mode == "preview":
            headers["Content-Disposition"] = f'inline; filename="{filename}"'
        else:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        def generate():
            for chunk in r.iter_content(chunk_size=262144):
                if chunk:
                    yield chunk

        return Response(generate(), status=status_code, headers=headers)

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
        "service": "Instagram Public Video API",
        "version": "2.1"
    })


# ==========================
# START
# ==========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
