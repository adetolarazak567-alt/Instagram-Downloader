import requests
import re
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

session = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)"
}

# ==============================
# Extract Instagram video
# ==============================
def get_instagram_video(url):

    r = session.get(url, headers=HEADERS, timeout=20)

    if r.status_code != 200:
        raise Exception("Failed to access Instagram")

    soup = BeautifulSoup(r.text, "html.parser")

    # Look for og:video
    video = soup.find("meta", property="og:video")

    if video:
        return video["content"]

    # fallback regex
    match = re.search(r'"video_url":"([^"]+)"', r.text)

    if match:
        return match.group(1).replace("\\u0026", "&")

    raise Exception("Video not found")

# ==============================
# FETCH API
# ==============================
@app.route("/api/fetch", methods=["POST"])
def fetch():

    data = request.get_json()
    url = data.get("url")

    if not url or "instagram.com" not in url:
        return jsonify({"success": False, "message": "Invalid URL"}), 400

    try:

        video_url = get_instagram_video(url)

        return jsonify({
            "success": True,
            "videoUrl": video_url
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ==============================
# DOWNLOAD
# ==============================
@app.route("/api/download")
def download():

    video_url = request.args.get("url")

    if not video_url:
        return jsonify({"success": False}), 400

    r = session.get(video_url, stream=True)

    headers = {
        "Content-Type": "video/mp4",
        "Content-Disposition": 'attachment; filename="instagram_video.mp4"'
    }

    return Response(r.iter_content(8192), headers=headers)


# ==============================
# HOME
# ==============================
@app.route("/")
def home():
    return "Instagram Downloader API Running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)