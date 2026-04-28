import os
import certifi
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)
CORS(app)  # 允许跨域，解决前端调用问题

# --- 1. 数据库配置 ---
MONGO_URI = os.environ.get("MONGO_URI")

# 优化连接参数，增加重试和超时控制
client = MongoClient(
    MONGO_URI,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000, # 5秒连接不上就报错，防止进程卡死
    connectTimeoutMS=10000
)

db = client['gangan_wheel_db']
collection = db['messages']

# 这一步非常重要：在启动时不强制阻塞，防止连接失败导致整个服务被 Render 杀掉
try:
    client.admin.command('ping')
    print("✅ 成功连接到 MongoDB Atlas！")
except Exception as e:
    print(f"⚠️ 数据库暂时无法连接，请检查 MONGO_URI 或 IP 白名单: {e}")


# --- 2. 路由逻辑 ---

@app.route('/api/messages', methods=['GET'])
def get_messages():
    try:
        # 从数据库读取最新的 50 条消息，按 ID 倒序排列
        msgs = list(collection.find().sort("_id", -1).limit(50))

        results = []
        for m in reversed(msgs):  # 反转回正序显示在前端
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
        # 添加当前服务器时间
        data['time'] = datetime.now().strftime("%H:%M")
        # 直接插入到 MongoDB
        collection.insert_one(data)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    # 获取 Render 分配的端口，如果没有则默认 10000 (Render 默认端口)
    port = int(os.environ.get("PORT", 10000))
    # 必须监听 0.0.0.0
    app.run(host='0.0.0.0', port=port)
