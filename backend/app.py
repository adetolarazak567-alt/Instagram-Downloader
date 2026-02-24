# app.py
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import os
import time
import sqlite3

app = Flask(__name__)
CORS(app)

# ===== SQLITE DATABASE SETUP =====
conn = sqlite3.connect("instagram_stats.db", check_same_thread=False)
c = conn.cursor()

# Create stats table
c.execute("""
CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER
)
""")

# Initialize stats keys
for key in ["requests", "downloads", "videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)", (key, 0))

# Unique IPs table
c.execute("""
CREATE TABLE IF NOT EXISTS unique_ips (
    ip TEXT PRIMARY KEY
)
""")

# Download logs table
c.execute("""
CREATE TABLE IF NOT EXISTS download_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT,
    url TEXT,
    timestamp INTEGER
)
""")

conn.commit()


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

    # increment requests
    c.execute("UPDATE stats SET value = value + 1 WHERE key = 'requests'")

    ip = request.remote_addr

    data = request.get_json()
    url = data.get("url")
    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    # add unique ip
    c.execute("INSERT OR IGNORE INTO unique_ips (ip) VALUES (?)", (ip,))

    try:
        info = fetch_instagram_video(url)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    # increment stats
    c.execute("UPDATE stats SET value = value + 1 WHERE key = 'downloads'")
    c.execute("UPDATE stats SET value = value + 1 WHERE key = 'videos_served'")

    # add log
    c.execute(
        "INSERT INTO download_logs (ip, url, timestamp) VALUES (?, ?, ?)",
        (ip, url, int(time.time()))
    )

    conn.commit()

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

    # fetch stats
    c.execute("SELECT key, value FROM stats")
    stats_data = dict(c.fetchall())

    # unique ips count
    c.execute("SELECT COUNT(*) FROM unique_ips")
    unique_ips_count = c.fetchone()[0]

    # logs
    c.execute("SELECT ip, url, timestamp FROM download_logs")
    logs = [{"ip": ip, "url": url, "timestamp": ts} for ip, url, ts in c.fetchall()]

    return jsonify({
        "requests": stats_data.get("requests", 0),
        "downloads": stats_data.get("downloads", 0),
        "videos_served": stats_data.get("videos_served", 0),
        "unique_ips": unique_ips_count,
        "download_logs": logs
    })


# ===== ADMIN RESET =====
ADMIN_PASSWORD = "razzyadminX567"

@app.route("/admin/reset", methods=["POST"])
def reset_stats():

    data = request.get_json()
    password = data.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "message": "Wrong password"}), 401

    # reset stats
    for key in ["requests", "downloads", "videos_served"]:
        c.execute("UPDATE stats SET value = 0 WHERE key = ?", (key,))

    # clear unique ips
    c.execute("DELETE FROM unique_ips")

    # clear logs
    c.execute("DELETE FROM download_logs")

    conn.commit()

    return jsonify({"success": True})


# ===== Deployment run =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)