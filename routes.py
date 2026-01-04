"""
Web routes for API endpoints.

Provides health check and meeting API.
"""
from quart import Blueprint, request, jsonify
from telethon.tl.functions.account import UpdateEmojiStatusRequest
from telethon.tl.types import EmojiStatus

from logging_config import logger
from models import Schedule, Settings
from config import config

# Create blueprint for API routes
api_bp = Blueprint('api', __name__)

# Client will be set by register_routes()
_client = None


def register_routes(app, client):
    """
    Register API routes on the Quart app.

    Args:
        app: Quart application instance
        client: Telethon client instance
    """
    global _client
    _client = client
    app.register_blueprint(api_bp)


@api_bp.route("/health")
async def health():
    """Health check endpoint for Docker/Kubernetes."""
    is_connected = _client.is_connected()
    is_authorized = await _client.is_user_authorized() if is_connected else False

    status = {
        "status": "ok" if is_connected and is_authorized else "degraded",
        "telethon_connected": is_connected,
        "telethon_authorized": is_authorized,
    }

    status_code = 200 if status["status"] == "ok" else 503
    return status, status_code


@api_bp.route("/api/meeting", methods=["POST"])
async def meeting():
    """
    API endpoint for meeting status control (e.g., Zoom integration).

    Query parameters:
        action: 'start' or 'end'
        emoji_id: (optional for start) emoji document ID to set during meeting
        token: (optional) API token for authentication

    Examples:
        POST /api/meeting?action=start&emoji_id=5368324170671202286
        POST /api/meeting?action=start  (uses saved meeting emoji)
        POST /api/meeting?action=end
    """
    # Check token if configured
    if config.meeting_api_token:
        token = request.args.get('token') or request.headers.get('X-API-Token')
        if token != config.meeting_api_token:
            return jsonify({"error": "Invalid or missing API token"}), 401

    action = request.args.get('action')

    if action not in ('start', 'end'):
        return jsonify({"error": "Invalid action. Use 'start' or 'end'"}), 400

    if action == 'start':
        emoji_id = request.args.get('emoji_id')

        # If emoji_id not provided, use saved meeting emoji
        if not emoji_id:
            saved_emoji_id = Settings.get('meeting_emoji_id')
            if saved_emoji_id:
                emoji_id = saved_emoji_id
            else:
                return jsonify({
                    "error": "emoji_id is required. Set default via /meeting command or pass emoji_id parameter"
                }), 400

        try:
            emoji_id = int(emoji_id)
        except ValueError:
            return jsonify({"error": "emoji_id must be a number"}), 400

        # Create meeting schedule rule
        Schedule.start_meeting(emoji_id)
        logger.info(f"Meeting started with emoji_id: {emoji_id}")

        # Immediately update emoji status
        try:
            await _client(UpdateEmojiStatusRequest(
                emoji_status=EmojiStatus(document_id=emoji_id)
            ))
            logger.info(f"Emoji status updated to {emoji_id}")
        except Exception as e:
            logger.error(f"Failed to update emoji status: {e}")
            return jsonify({
                "status": "partial",
                "message": "Meeting rule created but failed to update emoji immediately",
                "error": str(e)
            }), 500

        return jsonify({
            "status": "ok",
            "action": "start",
            "emoji_id": emoji_id,
            "message": "Meeting started, emoji status updated"
        })

    else:  # action == 'end'
        was_active = Schedule.end_meeting()

        if was_active:
            logger.info("Meeting ended, rule removed")

            # Get scheduled emoji and apply it immediately
            scheduled_emoji_id = Schedule.get_current_emoji_id()
            if scheduled_emoji_id:
                try:
                    await _client(UpdateEmojiStatusRequest(
                        emoji_status=EmojiStatus(document_id=scheduled_emoji_id)
                    ))
                    logger.info(f"Emoji status restored to scheduled: {scheduled_emoji_id}")
                except Exception as e:
                    logger.error(f"Failed to restore emoji status: {e}")

            return jsonify({
                "status": "ok",
                "action": "end",
                "message": "Meeting ended, emoji status restored",
                "scheduled_emoji_id": scheduled_emoji_id
            })
        else:
            return jsonify({
                "status": "ok",
                "action": "end",
                "message": "No active meeting found"
            })
