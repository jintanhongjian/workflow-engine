import redis
try:
    r = redis.Redis(host='127.0.0.1', port=6379, db=0)
    print("Redis 连接成功:", r.ping())
except Exception as e:
    print("Redis 连接失败:", e)