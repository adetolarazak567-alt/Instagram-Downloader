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
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)

session = requests.Session()

# ===== SQLITE DATABASE =====
conn = sqlite3.connect("insta_stats.db", check_same_thread=False)
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER
)
''')

for key in ["requests", "downloads", "cache_hits", "videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)", (key, 0))

conn.commit()

# Unique IP table
c.execute('''
CREATE TABLE IF NOT EXISTS unique_ips (
    ip TEXT PRIMARY KEY
)
''')

# Download logs
c.execute('''
CREATE TABLE IF NOT EXISTS download_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT,
    url TEXT,
    timestamp INTEGER
)
''')

conn.commit()

# ===== CACHE =====
cache = {}

# ===== RANDOM STRING =====
def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# ===== CLEAN FILENAME =====
def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text[:120]

# ===== FETCH INSTAGRAM VIDEO =====
def fetch_instagram_video(url):

    ydl_opts = {
        "format": "best",
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        return {
            "video_url": info.get("url"),
            "title": info.get("title", "Instagram Video"),
            "author_name": info.get("uploader", "")
        }

# ===== FETCH API =====
@app.route("/api/fetch", methods=["POST"])
def fetch_video():

    ip = request.remote_addr
    data = request.get_json()
    url = data.get("url")

    url = url.split("?")[0]

    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid Instagram URL"}), 400

    # increment request
    c.execute("UPDATE stats SET value = value + 1 WHERE key='requests'")
    conn.commit()

    # unique ip
    c.execute("INSERT OR IGNORE INTO unique_ips (ip) VALUES (?)", (ip,))
    conn.commit()

    # ===== CACHE HIT =====
    if url in cache:

        video_url = cache[url]

        c.execute("UPDATE stats SET value = value + 1 WHERE key='cache_hits'")
        c.execute("UPDATE stats SET value = value + 1 WHERE key='downloads'")
        c.execute("UPDATE stats SET value = value + 1 WHERE key='videos_served'")

        c.execute(
            "INSERT INTO download_logs (ip,url,timestamp) VALUES (?,?,?)",
            (ip, url, int(time.time()))
        )

        conn.commit()

        return jsonify({
            "success": True,
            "videoUrl": video_url,
            "cached": True
        })

    # ===== FETCH VIDEO =====
    try:

        info = fetch_instagram_video(url)
        video_url = info["video_url"]

    except Exception as e:

        err = str(e).lower()

        if "login" in err or "cookies" in err:
            msg = "This Instagram post requires login."

        elif "private" in err:
            msg = "This Instagram post is private."

        elif "empty media response" in err:
            msg = "Instagram blocked this request. Try again."

        else:
            msg = "Failed to fetch video. The link may be invalid."

        return jsonify({
            "success": False,
            "message": msg
        }), 400

    # save cache
    cache[url] = video_url

    c.execute("UPDATE stats SET value = value + 1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value = value + 1 WHERE key='videos_served'")

    c.execute(
        "INSERT INTO download_logs (ip,url,timestamp) VALUES (?,?,?)",
        (ip, url, int(time.time()))
    )

    conn.commit()

    return jsonify({
        "success": True,
        "videoUrl": video_url,
        "title": info["title"],
        "author_name": info["author_name"],
        "cached": False
    })

# ===== DOWNLOAD ROUTE =====
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
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Type": "video/mp4"
        }

        return Response(r.iter_content(chunk_size=8192), headers=headers)

    except Exception as e:

        return jsonify({
            "success": False,
            "message": "Video download failed"
        }), 500

# ===== STATS =====
@app.route("/stats", methods=["GET"])
def get_stats():

    c.execute("SELECT key,value FROM stats")
    stats_data = dict(c.fetchall())

    c.execute("SELECT COUNT(*) FROM unique_ips")
    unique_ips_count = c.fetchone()[0]

    c.execute("SELECT ip,url,timestamp FROM download_logs")

    logs = [
        {"ip": ip, "url": url, "timestamp": ts}
        for ip, url, ts in c.fetchall()
    ]

    return jsonify({
        **stats_data,
        "unique_ips": unique_ips_count,
        "download_logs": logs
    })

# ===== ADMIN RESET =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

@app.route("/admin/reset", methods=["POST"])
def reset_stats():

    data = request.get_json()
    password = data.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "message": "Wrong password"}), 401

    for key in ["requests", "downloads", "cache_hits", "videos_served"]:
        c.execute("UPDATE stats SET value=0 WHERE key=?", (key,))

    c.execute("DELETE FROM unique_ips")
    c.execute("DELETE FROM download_logs")

    conn.commit()

    cache.clear()

    return jsonify({"success": True})

@app.route("/")
def home():
    return "ToolifyX API running"

# ===== START SERVER =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)