from flask import Flask, request, jsonify, send_from_directory, Response
import requests

app = Flask(__name__)

# === Serve frontend (index.html) ===
@app.route("/")
def home():
    return send_from_directory(".", "index.html")

# === API endpoint to fetch Instagram post info ===
@app.route("/api/fetch", methods=["POST"])
def fetch_post():
    try:
        data = request.get_json()
        url = data.get("url")

        if not url or "instagram.com" not in url:
            return jsonify({"success": False, "message": "Invalid Instagram URL."}), 400

        # Example: use oEmbed (works only for public posts)
        api_url = "https://api.instagram.com/oembed/?url=" + url
        r = requests.get(api_url)

        if r.status_code != 200:
            return jsonify({"success": False, "message": "Failed to fetch post."}), 500

        oembed = r.json()

        return jsonify({
            "success": True,
            "title": oembed.get("title", "Instagram Video"),
            "author_name": oembed.get("author_name"),
            "thumbnail": oembed.get("thumbnail_url"),
            "shortcode": oembed.get("media_id"),
            # NOTE: oEmbed doesn’t provide direct video url, needs scraper/proxy
            "videoUrl": url  
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
