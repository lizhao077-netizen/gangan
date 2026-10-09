import os
import certifi
import hmac
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timezone

app = Flask(__name__)
CORS(app, resources={
    r"/api/messages": {"origins": "*"},
    r"/api/gaixia/*": {"origins": "https://lizhao077-netizen.github.io"},
}, allow_headers=["Content-Type", "X-Access-Password"])

# --- Existing gangan database ---
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000
)
db = client['gangan_wheel_db']
collection = db['messages']
gaixia_collection = db['gaixia_shows']

try:
    client.admin.command('ping')
    print("✅ 成功连接到 MongoDB Atlas！")
except Exception as e:
    print(f"⚠️ 数据库暂时无法连接，请检查 MONGO_URI 或 IP 白名单: {e}")

# --- Existing gangan message API (preserved) ---
@app.route('/api/messages', methods=['GET'])
def get_messages():
    try:
        msgs = list(collection.find().sort("_id", -1).limit(50))
        results = []
        for m in reversed(msgs):
            results.append({
                "user": m.get('user'),
                "content": m.get('content'),
                "avatar": m.get('avatar'),
                "time": m.get('time', datetime.now().strftime("%H:%M"))
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/messages', methods=['POST'])
def save_message():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "无数据"}), 400
    try:
        data['time'] = datetime.now().strftime("%H:%M")
        collection.insert_one(data)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Gaixia show API: isolated collection, shared MongoDB and Render service ---
def _gaixia_admin_ok():
    expected = os.environ.get("GAIXIA_ADMIN_PASSWORD")
    supplied = request.headers.get("X-Access-Password", "")
    return bool(expected) and hmac.compare_digest(supplied, expected)

def _valid_show(show):
    if not isinstance(show, dict) or not isinstance(show.get("rounds"), list):
        return False
    for round_data in show["rounds"]:
        if not isinstance(round_data, dict) or not isinstance(round_data.get("lines"), list):
            return False
        for line in round_data["lines"]:
            if not isinstance(line, dict) or not isinstance(line.get("text"), str) or len(line["text"]) > 120:
                return False
    return len(str(show).encode("utf-8")) <= 500000

def _no_store(response):
    if isinstance(response, tuple):
        body, status = response
        body.headers["Cache-Control"] = "no-store, max-age=0"
        return body, status
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

@app.route('/api/gaixia/published', methods=['GET'])
def get_gaixia_published():
    try:
        saved = gaixia_collection.find_one({"_id": "main"}, {"published": 1, "published_at": 1})
        if not saved or not saved.get("published"):
            return _no_store((jsonify({"error": "暂无已发布的演出"}), 404))
        return _no_store(jsonify({"show": saved["published"], "publishedAt": saved.get("published_at")}))
    except Exception:
        return _no_store((jsonify({"error": "云端读取失败，请稍后重试"}), 500))

@app.route('/api/gaixia/admin', methods=['GET', 'PUT', 'POST'])
def manage_gaixia_show():
    if not os.environ.get("GAIXIA_ADMIN_PASSWORD"):
        return _no_store((jsonify({"error": "Render 服务尚未读取到 GAIXIA_ADMIN_PASSWORD，请检查环境组关联和部署状态"}), 503))
    if not _gaixia_admin_ok():
        return _no_store((jsonify({"error": "管理密码不匹配，请输入该环境变量 VALUE 中设置的原始密码"}), 401))
    if request.content_length and request.content_length > 600000:
        return _no_store((jsonify({"error": "请求内容超过限制"}), 413))
    try:
        if request.method == 'GET':
            saved = gaixia_collection.find_one({"_id": "main"}, {"draft": 1, "published_at": 1}) or {}
            return _no_store(jsonify({"draft": saved.get("draft"), "publishedAt": saved.get("published_at")}))
        payload = request.get_json(silent=True) or {}
        if request.method == 'PUT':
            draft = payload.get("draft")
            if not _valid_show(draft):
                return _no_store((jsonify({"error": "草稿格式无效或内容超出限制"}), 400))
            gaixia_collection.update_one(
                {"_id": "main"},
                {"$set": {"draft": draft, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
            return _no_store(jsonify({"ok": True}))
        if payload.get("action") != "publish":
            return _no_store((jsonify({"error": "无效操作"}), 400))
        saved = gaixia_collection.find_one({"_id": "main"}, {"draft": 1})
        if not saved or not _valid_show(saved.get("draft")):
            return _no_store((jsonify({"error": "没有可发布的有效草稿"}), 409))
        published_at = datetime.now(timezone.utc).isoformat()
        gaixia_collection.update_one(
            {"_id": "main"},
            {"$set": {"published": saved["draft"], "published_at": published_at}},
            upsert=True
        )
        return _no_store(jsonify({"ok": True, "publishedAt": published_at}))
    except Exception:
        return _no_store((jsonify({"error": "云端管理操作失败，请稍后重试"}), 500))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

