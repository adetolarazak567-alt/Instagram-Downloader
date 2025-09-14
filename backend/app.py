# app.py
from flask import Flask, request, jsonify, send_from_directory, Response
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# === Serve frontend (index.html) ===
@app.route("/")
def home():
    return send_from_directory(".", "index.html")

# === Helper: fetch direct video URL from Instagram post/reel/igtv ===
def get_instagram_video_url(insta_url):
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(insta_url, headers=headers)
        if r.status_code != 200:
            return None, "Failed to fetch Instagram post"

        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        # Look for JSON in window._sharedData
        scripts = soup.find_all("script", text=re.compile("window._sharedData"))
        for script in scripts:
            json_text = re.search(r'window\._sharedData\s*=\s*(\{.*\});', script.string)
            if json_text:
                data = json_text.group(1)
                # Search for video_url
                match = re.search(r'"video_url":"([^"]+)"', data)
                if match:
                    video_url = match.group(1).replace("\\u0026", "&")
                    return video_url, None

        # Fallback: look for meta property="og:video"
        og_video = soup.find("meta", property="og:video")
        if og_video and og_video.get("content"):
            return og_video["content"], None

        return None, "Video URL not found. Make sure the post/reel/igtv is public."
    except Exception as e:
        return None, str(e)

# === API endpoint to fetch Instagram post info ===
@app.route("/api/fetch", methods=["POST"])
def fetch_post():
    try:
        data = request.get_json()
        url = data.get("url")

        if not url or "instagram.com" not in url:
            return jsonify({"success": False, "message": "Invalid Instagram URL."}), 400

        # Get direct video URL
        video_url, error = get_instagram_video_url(url)
        if not video_url:
            return jsonify({"success": False, "message": error}), 500

        # Try to get title & author from oEmbed
        oembed_url = "https://api.instagram.com/oembed/?url=" + url
        r = requests.get(oembed_url)
        title = "Instagram Video"
        author_name = ""
        if r.status_code == 200:
            oembed = r.json()
            title = oembed.get("title", title)
            author_name = oembed.get("author_name", "")

        return jsonify({
            "success": True,
            "title": title,
            "author_name": author_name,
            "videoUrl": video_url
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# === API endpoint to proxy download ===
@app.route("/api/download")
def download_video():
    video_url = request.args.get("url")
    if not video_url:
        return "Missing video url", 400

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
