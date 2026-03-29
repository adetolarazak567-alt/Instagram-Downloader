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
import json

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

for key in ["requests","downloads","cache_hits","videos_served"]:
    c.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,?)",(key,0))

conn.commit()

c.execute('''
CREATE TABLE IF NOT EXISTS unique_ips (
ip TEXT PRIMARY KEY
)
''')

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
    return ''.join(random.choices(string.ascii_letters + string.digits,k=length))

# ===== INSTAGRAM FETCH (yt-dlp) =====
def fetch_with_ytdlp(url):

    ydl_opts = {
        "format":"best",
        "quiet":True,
        "noplaylist":True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(url, download=False)

        return {
            "video_url": info.get("url"),
            "title": info.get("title","Instagram Video"),
            "author_name": info.get("uploader","")
        }

# ===== FALLBACK METHOD =====
def fetch_with_json(url):

    headers = {
        "User-Agent":"Mozilla/5.0"
    }

    r = session.get(url+"?__a=1&__d=dis",headers=headers)

    data = r.json()

    video = data["graphql"]["shortcode_media"]["video_url"]

    return {
        "video_url": video,
        "title": "Instagram Video",
        "author_name": ""
    }

# ===== FETCH API =====
@app.route("/api/fetch", methods=["POST"])
def fetch_video():

    ip = request.remote_addr
    data = request.get_json()

    url = data.get("url")

    url = url.split("?")[0]

    if not url or "instagram.com" not in url:
        return jsonify({"success":False,"message":"Invalid Instagram URL"}),400

    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    c.execute("INSERT OR IGNORE INTO unique_ips (ip) VALUES (?)",(ip,))
    conn.commit()

    # ===== CACHE =====
    if url in cache:

        video_url = cache[url]

        return jsonify({
            "success":True,
            "videoUrl":video_url,
            "cached":True
        })

    # ===== TRY YT-DLP =====
    try:

        info = fetch_with_ytdlp(url)
        video_url = info["video_url"]

    except Exception:

        # ===== FALLBACK JSON =====
        try:

            info = fetch_with_json(url)
            video_url = info["video_url"]

        except Exception:

            return jsonify({
                "success":False,
                "message":"Failed to fetch video. The post may be private."
            }),400

    cache[url] = video_url

    c.execute("UPDATE stats SET value=value+1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value=value+1 WHERE key='videos_served'")

    c.execute(
        "INSERT INTO download_logs (ip,url,timestamp) VALUES (?,?,?)",
        (ip,url,int(time.time()))
    )

    conn.commit()

    return jsonify({
        "success":True,
        "videoUrl":video_url,
        "title":info["title"],
        "author_name":info["author_name"],
        "cached":False
    })

# ===== DOWNLOAD ROUTE =====
@app.route("/api/download")
def download_video():

    video_url = request.args.get("url")

    if not video_url:
        return jsonify({"success":False}),400

    r = session.get(video_url,stream=True)

    filename = f"ToolifyX-{random_string()}.mp4"

    headers = {
        "Content-Disposition":f'inline; filename="{filename}"',
        "Content-Type":"video/mp4"
    }

    return Response(r.iter_content(8192),headers=headers)

# ===== HOME =====
@app.route("/")
def home():
    return "ToolifyX API running"

# ===== START =====
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000,threaded=True)