from flask import Flask, request, jsonify
import urllib.request
import urllib.error
from bs4 import BeautifulSoup
import socket
import ssl
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# === Google Sheets Setup ===
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
import json
import os
from oauth2client.service_account import ServiceAccountCredentials

# Load Google credentials from environment variable (safe for Render)
creds_json = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(creds_json)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")  # <-- Add this line
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
gc = gspread.authorize(creds)

# === Keywords ===
POSITIVE_403_KEYWORDS = [
    "engineering", "services", "solutions", "projects", "clients",
    "contact", "about us", "industries", "management", "power", "energy"
]

JUNK_PHRASES = [
    "expired domain", "buy now on godaddy", "plesk",
    "web server's default page", "index of /", "coming soon",
    "this domain is for sale", "future home of",
    "this site can’t be reached", "no web site at this address",
    "log in to plesk"
]

def is_junk(text):
    return any(phrase in text.lower() for phrase in JUNK_PHRASES)

def count_positive_keywords(text):
    return sum(1 for kw in POSITIVE_403_KEYWORDS if kw in text.lower())

def normalize_url(url):
    if not url.lower().startswith(("http://", "https://")):
        return "http://" + url
    return url

# === Website Checker ===
def get_site_status(url):
    url = normalize_url(url)
    headers = {'User-Agent': 'Mozilla/5.0'}

    def fetch(url, context=None):
        req = urllib.request.Request(url, headers=headers)
        return urllib.request.urlopen(req, timeout=10, context=context)

    try:
        try:
            response = fetch(url)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                response = fetch(url, context=ctx)
            else:
                raise

        html = response.read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        tags = {tag.name for tag in soup.find_all()}
        tag_count = len(tags)
        text_len = len(text)
        keyword_count = count_positive_keywords(text)

        if is_junk(text):
            return ("no", "placeholder / junk content")
        if text_len < 100 and tag_count < 8 and keyword_count == 0:
            return ("no", "low content")
        return ("yes", "")
    except Exception as ex:
        return ("no", f"error: {ex}")

# === Flask endpoint ===
@app.route("/check-websites", methods=["POST"])
def check_websites():
    try:
        sheet = gc.open("Website Status Check").sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)

        if "Website" not in df.columns:
            return jsonify({"error": "Missing 'Website' column"}), 400

        df["Website"] = df["Website"].apply(normalize_url)
        results = [get_site_status(url) for url in df["Website"]]
        result_df = pd.DataFrame(results, columns=["Yes/No", "Explanation"])

        website_idx = df.columns.get_loc("Website")
        left = df.iloc[:, :website_idx + 1]
        right = df.iloc[:, website_idx + 1:]
        final_df = pd.concat([left, result_df, right], axis=1)

        sheet.clear()
        sheet.update([final_df.columns.values.tolist()] + final_df.values.tolist())
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
    
