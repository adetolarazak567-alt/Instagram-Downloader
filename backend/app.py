# app.py
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import time

app = Flask(__name__)
CORS(app)

# ===== Stats & Cache =====
stats = {
    "requests": 0,
    "downloads": 0,
    "cache_hits": 0,
    "videos_served": 0,
    "unique_ips": set(),
    "download_logs": []
}
cache = {}

# ===== Download endpoint =====
@app.route("/download", methods=["POST"])
def download_video():
    stats["requests"] += 1
    ip = request.remote_addr

    data = request.get_json()
    url = data.get("url")
    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "error": "Invalid Instagram URL"}), 400

    stats["unique_ips"].add(ip)

    # Check cache
    if url in cache:
        stats["cache_hits"] += 1
        video_url = cache[url]
    else:
        try:
            ydl_opts = {"format": "best", "quiet": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_url = info.get("url")
                if not video_url:
                    return jsonify({"success": False, "error": "Could not extract video"}), 500
                cache[url] = video_url
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    stats["downloads"] += 1
    stats["videos_served"] += 1
    stats["download_logs"].append({
        "ip": ip,
        "url": url,
        "timestamp": int(time.time())
    })

    return jsonify({"success": True, "videoUrl": video_url})

# ===== Stats endpoint =====
@app.route("/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "requests": stats["requests"],
        "downloads": stats["downloads"],
        "cache_hits": stats["cache_hits"],
        "videos_served": stats["videos_served"],
        "unique_ips": len(stats["unique_ips"]),
        "download_logs": stats["download_logs"]
    })

# ===== Deployment safe run =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)