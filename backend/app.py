# instagram_app.py
import time
import requests
import random
import string
import re
import sqlite3
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

session = requests.Session()

# ====== SQLITE DATABASE SETUP ======
conn = sqlite3.connect("insta_stats.db", check_same_thread=False)
c = conn.cursor()

# Create stats table
c.execute('''
CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER
)
''')
for key in ["requests", "downloads", "cache_hits", "videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)", (key, 0))
conn.commit()

# Table for unique IPs
c.execute('''
CREATE TABLE IF NOT EXISTS unique_ips (
    ip TEXT PRIMARY KEY
)
''')

# Table for download logs
c.execute('''
CREATE TABLE IF NOT EXISTS download_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT,
    url TEXT,
    timestamp INTEGER
)
''')
conn.commit()

# ====== CACHE ======
cache = {}  # url -> video_url

# ====== RANDOM STRING ======
def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# ====== CLEAN FILENAME ======
def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text[:120]

# ====== FETCH INSTAGRAM VIDEO ======
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
        return {
            "video_url": info.get("url"),
            "title": info.get("title", "Instagram Video"),
            "author_name": info.get("uploader", "")
        }

# ====== DOWNLOAD API ======
@app.route("/api/fetch", methods=["POST"])
def fetch_video():
    ip = request.remote_addr
    data = request.get_json()
    url = data.get("url")

    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    # increment requests
    c.execute("UPDATE stats SET value = value + 1 WHERE key='requests'")
    conn.commit()

    # add unique IP
    c.execute("INSERT OR IGNORE INTO unique_ips (ip) VALUES (?)", (ip,))
    conn.commit()

    # ===== CACHE HIT =====
    if url in cache:
        video_url = cache[url]
        c.execute("UPDATE stats SET value = value + 1 WHERE key='cache_hits'")
        c.execute("UPDATE stats SET value = value + 1 WHERE key='downloads'")
        c.execute("UPDATE stats SET value = value + 1 WHERE key='videos_served'")
        # log download
        c.execute("INSERT INTO download_logs (ip,url,timestamp) VALUES (?,?,?)",
                  (ip, url, int(time.time())))
        conn.commit()
        return jsonify({"success": True, "videoUrl": video_url, "cached": True})

    # ===== FETCH VIDEO =====
    try:
        info = fetch_instagram_video(url)
        video_url = info["video_url"]
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    # store in cache
    cache[url] = video_url

    # update stats
    c.execute("UPDATE stats SET value = value + 1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value = value + 1 WHERE key='videos_served'")
    c.execute("INSERT INTO download_logs (ip,url,timestamp) VALUES (?,?,?)",
              (ip, url, int(time.time())))
    conn.commit()

    return jsonify({
        "success": True,
        "videoUrl": video_url,
        "title": info["title"],
        "author_name": info["author_name"],
        "cached": False
    })

# ====== FILE SERVING / PREVIEW ======
@app.route("/api/download")
def download_video():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"success": False, "message": "No video URL"}), 400

    try:
        r = session.get(video_url, stream=True, timeout=60)
        rand = random_string()
        filename = f"ToolifyX Downloader-{rand}.mp4"

        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',  # preview support
            "Content-Type": "video/mp4"
        }

        return Response(r.iter_content(chunk_size=8192), headers=headers)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ====== STATS ROUTE ======
@app.route("/stats", methods=["GET"])
def get_stats():
    c.execute("SELECT key,value FROM stats")
    stats_data = dict(c.fetchall())

    c.execute("SELECT COUNT(*) FROM unique_ips")
    unique_ips_count = c.fetchone()[0]

    c.execute("SELECT ip,url,timestamp FROM download_logs")
    logs = [{"ip": ip, "url": url, "timestamp": ts} for ip, url, ts in c.fetchall()]

    return jsonify({
        **stats_data,
        "unique_ips": unique_ips_count,
        "download_logs": logs
    })

# ====== ADMIN RESET ======
ADMIN_PASSWORD = "razzyadminX567"

@app.route("/admin/reset", methods=["POST"])
def reset_stats():
    data = request.get_json()
    password = data.get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "message": "Wrong password"}), 401

    # reset stats
    for key in ["requests", "downloads", "cache_hits", "videos_served"]:
        c.execute("UPDATE stats SET value=0 WHERE key=?", (key,))

    # clear unique IPs and logs
    c.execute("DELETE FROM unique_ips")
    c.execute("DELETE FROM download_logs")
    conn.commit()

    # clear in-memory cache
    cache.clear()

    return jsonify({"success": True})

# ====== START SERVER ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)