from functools import wraps
from flask import request, jsonify


def authorize(f):
    """
    Test-mode authorization decorator.

    Expects the header:
        Authorization: Bearer <user_id>

    where <user_id> is the plain integer primary key of the user in
    the college_account_new table.

    This is intentionally simple for local Postman testing.
    Replace the body of this decorator with real JWT verification
    (e.g. using PyJWT) before connecting to production.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({
                "status": 401,
                "message": "Unauthorized — send: Authorization: Bearer <user_id>"
            }), 401

        token = auth[7:].strip()
        try:
            user_id = int(token)
        except ValueError:
            return jsonify({
                "status": 401,
                "message": "Invalid token — for testing, the token must be a numeric user_id"
            }), 401

        user = {'user_id': user_id}
        return f(user, *args, **kwargs)

    return decorated
