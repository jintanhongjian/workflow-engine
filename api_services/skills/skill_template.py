# 第一行会被抓取为 Function.description。
# :param xxx: 后的文字会被抓取为参数的 description。
# int 注解会让 Gemini 知道该传数字而不是字符串。

def query_orders(user_id: str, limit: int = 10):
    """
    查询用户的订单记录。
    :param user_id: 用户的唯一识别ID
    :param limit: 返回的最大条数，默认为10
    """
    return [...]