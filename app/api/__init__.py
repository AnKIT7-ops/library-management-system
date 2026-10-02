from flask import request


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def int_arg(name, default):
    return request.args.get(name, default, type=int)
