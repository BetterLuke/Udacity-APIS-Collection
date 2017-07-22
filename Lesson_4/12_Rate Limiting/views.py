from redis import Redis
redis = Redis()

import time
from functools import update_wrapper
from flask import request, g
from flask import Flask, jsonify

app = Flask(__name__)


class RateLimit(object):
    expiration_window = 10 #键在redis中额外存活的10秒

    def __init__(self, key_prefix, limit, per, send_x_headers):
        self.reset = (int(time.time()) // per) * per + per #初始的时间戳
        self.key = key_prefix + str(self.reset)
        self.limit = limit
        self.per = per
        self.send_x_headers = send_x_headers
        p = redis.pipeline()
        p.incr(self.key)
        p.expireat(self.key, self.reset + self.expiration_window) # 在键per时间存活的之外，额外的增加的时间是为了这样防止客户端与服务端两者之间时钟之间的同步出现问题导致redis出现问题
        self.current = min(p.execute()[0], limit) #如果超过limit返回的就是limit

    remaining = property(lambda x: x.limit - x.current) #返回剩余的请求余量，结果等于0的时候就是超过了
    over_limit = property(lambda x: x.current >= x.limit) #如果超过了限制就会返回true


def get_view_rate_limit():
    return getattr(g, '_view_rate_limit', None)


def on_over_limit(limit): 
    '''
    处理超过请求限制的函数：让超过限制后，会传过来一个RateLimite对象，可以取出来里面有用的信息，比如操作Redis
    这里只是返回一个错误的字符串提示信息，实际中可以返回给用户一个temple，更美观。
    这也就解释了为什么下面的ratelimit函数里没有使用lambda的方式，因为这里只有一行代码是简化的方式，
    实际中，如果出发访问限制后的操作会很多。
    '''
    return (jsonify({'data': 'You hit the rate limit', 'error': '429'}), 429)


def ratelimit(limit, per=300, send_x_headers=True,
              over_limit=on_over_limit, #为什么不用lambda的方式? 已解决
              scope_func=lambda: request.remote_addr,
              key_func=lambda: request.endpoint):
    '''
    scope_func can get user ip
    key_func can get request URL
    '''
    def decorator(f):
        def rate_limited(*args, **kwargs):
            key = 'rate-limit/%s/%s/' % (key_func(), scope_func())
            rlimit = RateLimit(key, limit, per, send_x_headers)
            g._view_rate_limit = rlimit
            if over_limit is not None and rlimit.over_limit:
                return over_limit(rlimit)   #如果突破了限制就返回错误信息，否则继续循环运行装饰过的f函数
            return f(*args, **kwargs)
        return update_wrapper(rate_limited, f)
    return decorator


@app.after_request
def inject_x_rate_headers(response):
    limit = get_view_rate_limit()
    if limit and limit.send_x_headers: #limit.send_x_headers是一个布尔值
        h = response.headers
        h.add('X-RateLimit-Remaining', str(limit.remaining))
        h.add('X-RateLimit-Limit', str(limit.limit))
        h.add('X-RateLimit-Reset', str(limit.reset))
    return response


@app.route('/rate-limited')
@ratelimit(limit=300, per=30 * 1)
def index():
    return jsonify({'response': 'This is a rate limited response'})


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
