import json
from api.security import valid_session
from Advanced_crawl.advanced_crawl import handle_payload

def _handle_request(request):
    if request.method != "POST":
        return {"statusCode": 405, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "POST only"})}
    if not valid_session(request):
        return {"statusCode": 401, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"}, "body": json.dumps({"error": "Authentication required"})}
    return handle_payload(request.body)
