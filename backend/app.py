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

# ==========================
# METHOD 1
# MOBILE API SCRAPE
# ==========================

def fetch_mobile_api(url):

    headers={
        "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"
    }

    r=session.get(url+"?__a=1&__d=dis",headers=headers)

    if r.status_code!=200:
        return None

    data=r.json()

    media=data.get("graphql",{}).get("shortcode_media")

    if not media:
        return None

    if media.get("video_url"):
        return media["video_url"]

    return None


# ==========================
# METHOD 2
# PAGE SCRAPE
# ==========================

def fetch_html_scrape(url):

    headers={"User-Agent":"Mozilla/5.0"}

    r=session.get(url,headers=headers)

    if r.status_code!=200:
        return None

    soup=BeautifulSoup(r.text,"html.parser")

    metas=soup.find_all("meta")

    for m in metas:
        if m.get("property")=="og:video":
            return m.get("content")

    return None


# ==========================
# METHOD 3
# YT-DLP FALLBACK
# ==========================

def fetch_ytdlp(url):

    ydl_opts={
        "quiet":True,
        "format":"best",
        "noplaylist":True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info=ydl.extract_info(url,download=False)

        if "formats" in info:

            for f in reversed(info["formats"]):

                if f.get("ext")=="mp4":
                    return f["url"]

    return None


# ==========================
# FETCH CONTROLLER
# ==========================

def get_video(url):

    # cache
    if url in cache:
        return cache[url]

    # try methods
    video=fetch_mobile_api(url)

    if not video:
        video=fetch_html_scrape(url)

    if not video:
        video=fetch_ytdlp(url)

    if video:
        cache[url]=video

    return video


# ==========================
# FETCH API
# ==========================

@app.route("/api/fetch",methods=["POST"])
def fetch():

    data=request.get_json()
    url=data.get("url")

    if not url:
        return jsonify({"success":False})

    c.execute("UPDATE stats SET value=value+1 WHERE key='requests'")
    conn.commit()

    video=get_video(url)

    if not video:
        return jsonify({"success":False,"message":"Failed to fetch"}),500

    c.execute("UPDATE stats SET value=value+1 WHERE key='downloads'")
    c.execute("UPDATE stats SET value=value+1 WHERE key='videos_served'")
    conn.commit()

    return jsonify({
        "success":True,
        "videoUrl":video
    })


# ==========================
# DOWNLOAD
# ==========================

@app.route("/api/download")
def download():

    url=request.args.get("url")

    r=session.get(url,stream=True)

    filename=f"ToolifyX-{random_string()}.mp4"

    headers={
        "Content-Disposition":f'attachment; filename="{filename}"',
        "Content-Type":"video/mp4"
    }

    return Response(r.iter_content(8192),headers=headers)


# ==========================
# HOME
# ==========================

@app.route("/")
def home():
    return "Instagram Downloader API Running"


# ==========================
# START
# ==========================

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000)