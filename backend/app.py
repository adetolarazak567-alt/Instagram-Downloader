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

# ================= DATABASE =================
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

# ================= CACHE =================
cache = {}

# ================= RANDOM NAME =================
def random_string(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits,k=length))

# ================= METHOD 1 (YT-DLP) =================
def fetch_with_ytdlp(url):

    ydl_opts = {
        "quiet": True,
        "format": "best",
        "skip_download": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "noplaylist": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(url, download=False)

        if "entries" in info:
            info = info["entries"][0]

        formats = info.get("formats", [])

        if not formats:
            raise Exception("No formats")

        video = formats[-1]["url"]

        return video

# ================= METHOD 2 (EMBED SCRAPE) =================
def fetch_from_embed(url):

    headers = {
        "User-Agent":"Mozilla/5.0"
    }

    r = session.get(url + "embed/", headers=headers)

    match = re.search(r'"video_url":"([^"]+)"', r.text)

    if not match:
        raise Exception("Embed failed")

    video = match.group(1).replace("\\u0026","&")

    return video

# ================= METHOD 3 (META TAG) =================
def fetch_from_meta(url):

    headers = {
        "User-Agent":"Mozilla/5.0"
    }

    r = session.get(url, headers=headers)

    match = re.search(r'property="og:video" content="([^"]+)"', r.text)

    if not match:
        raise Exception("Meta failed")

    return match.group(1)

# ================= FETCH API =================
@app.route("/api/fetch", methods=["POST"])
def fetch_video():

    data = request.get_json()
    ip = request.remote_addr

    url = data.get("url")

    if not url:
        return jsonify({"success":False,"message":"No URL provided"}),400

    url = url.split("?")[0]

    if "instagram.com" not in url:
        return jsonify({"success":False,"message":"Invalid Instagram URL"}),400

    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    # ===== CACHE =====
    if url in cache:

        c.execute("UPDATE stats SET value=value+1 WHERE key='cache_hits'")
        conn.commit()

        return jsonify({
            "success":True,
            "videoUrl":cache[url],
            "cached":True
        })

    video = None

    # ===== TRY METHOD 1 =====
    try:
        video = fetch_with_ytdlp(url)
    except:
        pass

    # ===== TRY METHOD 2 =====
    if not video:
        try:
            video = fetch_from_embed(url)
        except:
            pass

    # ===== TRY METHOD 3 =====
    if not video:
        try:
            video = fetch_from_meta(url)
        except:
            pass

    if not video:
        return jsonify({
            "success":False,
            "message":"Failed to fetch video"
        }),400

    cache[url] = video

    c.execute("UPDATE stats SET value=value+1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value=value+1 WHERE key='videos_served'")
    conn.commit()

    return jsonify({
        "success":True,
        "videoUrl":video,
        "cached":False
    })

# ================= DOWNLOAD =================
@app.route("/api/download")
def download_video():

    video_url = request.args.get("url")

    if not video_url:
        return jsonify({"success":False}),400

    r = session.get(video_url, stream=True)

    filename = f"ToolifyX-{random_string()}.mp4"

    headers = {
        "Content-Disposition":f'inline; filename="{filename}"',
        "Content-Type":"video/mp4"
    }

    return Response(r.iter_content(8192), headers=headers)

# ================= STATS =================
@app.route("/stats")
def stats():

    data = {}

    for row in c.execute("SELECT key,value FROM stats"):
        data[row[0]] = row[1]

    return jsonify(data)

# ================= HOME =================
@app.route("/")
def home():
    return "ToolifyX Instagram API Running"

# ================= START =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)