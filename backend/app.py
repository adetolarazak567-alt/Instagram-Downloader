import time
import requests
import random
import string
import sqlite3
import re
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

session = requests.Session()

# ===== SQLITE DATABASE =====
conn = sqlite3.connect("insta_stats.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS stats (
key TEXT PRIMARY KEY,
value INTEGER
)
""")

for key in ["requests","downloads","cache_hits","videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,?)",(key,0))

conn.commit()

# ===== CACHE =====
cache = {}

# ===== RANDOM STRING =====
def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits,k=length))

# ===== CLEAN FILE NAME =====
def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return text[:120]

# ===== FETCH INSTAGRAM VIDEO =====
def fetch_instagram_video(url):

    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "format": "best",
        "nocheckcertificate": True,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0"
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(url, download=False)

        video_url = None

        # NEW METHOD (IMPORTANT)
        if "formats" in info:
            formats = info["formats"]

            # pick best mp4
            for f in reversed(formats):
                if f.get("ext") == "mp4" and f.get("url"):
                    video_url = f["url"]
                    break

        if not video_url:
            raise Exception("Instagram blocked the request")

        return {
            "video_url": video_url,
            "title": info.get("title","Instagram Video"),
            "author": info.get("uploader","")
        }

# ===== FETCH API =====
@app.route("/api/fetch", methods=["POST"])
def fetch_video():

    data = request.get_json()
    url = data.get("url")

    if not url or "instagram.com" not in url:
        return jsonify({"success":False,"message":"Invalid URL"}),400

    # stats
    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    # cache
    if url in cache:
        return jsonify({
            "success":True,
            "videoUrl":cache[url],
            "cached":True
        })

    try:

        info = fetch_instagram_video(url)

        video_url = info["video_url"]

    except Exception as e:

        return jsonify({
            "success":False,
            "message":str(e)
        }),500

    cache[url] = video_url

    c.execute("UPDATE stats SET value=value+1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value=value+1 WHERE key='videos_served'")
    conn.commit()

    return jsonify({
        "success":True,
        "videoUrl":video_url,
        "title":info["title"],
        "author":info["author"]
    })

# ===== DOWNLOAD =====
@app.route("/api/download")
def download():

    video_url = request.args.get("url")

    if not video_url:
        return jsonify({"success":False}),400

    r = session.get(video_url,stream=True)

    filename = f"ToolifyX-{random_string()}.mp4"

    headers = {
        "Content-Disposition":f'attachment; filename="{filename}"',
        "Content-Type":"video/mp4"
    }

    return Response(r.iter_content(8192),headers=headers)

# ===== HOME =====
@app.route("/")
def home():
    return "ToolifyX Instagram API running"

# ===== START =====
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000)