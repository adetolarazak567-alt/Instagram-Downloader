# app.py
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import os
import time

app = Flask(__name__)
CORS(app)

# ===== Stats =====
stats = {
    "requests": 0,
    "downloads": 0,
    "videos_served": 0,
    "unique_ips": set(),
    "download_logs": []
}

# ===== Helper: fetch Instagram video =====
def fetch_instagram_video(url):
    ydl_opts = {
        "format": "best",
        "quiet": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            )
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        video_url = info.get("url")
        return {
            "video_url": video_url,
            "title": info.get("title", "Instagram Video"),
            "author_name": info.get("uploader", "")
        }

# ===== Fetch endpoint =====
@app.route("/api/fetch", methods=["POST"])
def fetch_video():
    stats["requests"] += 1
    ip = request.remote_addr

    data = request.get_json()
    url = data.get("url")
    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    stats["unique_ips"].add(ip)

    try:
        info = fetch_instagram_video(url)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    stats["downloads"] += 1
    stats["videos_served"] += 1
    stats["download_logs"].append({
        "ip": ip,
        "url": url,
        "timestamp": int(time.time())
    })

    return jsonify({
        "success": True,
        "videoUrl": info["video_url"],
        "title": info["title"],
        "author_name": info["author_name"]
    })

# ===== Download endpoint =====
@app.route("/api/download")
def download_video():
    video_url = request.args.get("url")
    if not video_url:
        return "Missing video url", 400

    try:
        r = requests.get(video_url, stream=True)
        if r.status_code != 200:
            return "Failed to fetch video", 500

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        return Response(
            generate(),
            content_type="video/mp4",
            headers={"Content-Disposition": "attachment; filename=instagram.mp4"}
        )
    except Exception as e:
        return str(e), 500

# ===== Stats endpoint =====
@app.route("/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "requests": stats["requests"],
        "downloads": stats["downloads"],
        "videos_served": stats["videos_served"],
        "unique_ips": len(stats["unique_ips"]),
        "download_logs": stats["download_logs"]
    })

# ===== Deployment run =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)