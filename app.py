import os
import json
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

app = Flask(__name__)

# Get environment variables (use Azure App Service App Settings in production)
CONNECTION_STRING = os.getenv("COMMUNICATION_SERVICES_CONNECTION_STRING")
CHANNEL_ID = os.getenv("WHATSAPP_CHANNEL_ID")
MY_NUMBER = os.getenv("RECIPIENT_PHONE_NUMBER")

# Create ACS messaging client
messaging_client = NotificationMessagesClient.from_connection_string(CONNECTION_STRING)


@app.route("/webhook/messages", methods=["POST", "GET", "OPTIONS"])
def messages_webhook():
    """
    Handle Event Grid events from ACS (incoming messages, delivery reports, etc.)
    Also implement the subscription validation handshake as required by Azure Event Grid.
    """

    # For CloudEvents schema: Event Grid might send OPTIONS for abuse protection
    if request.method == "OPTIONS":
        # If using CloudEvents schema, respond with appropriate headers
        # Simplest: allow POST, etc.
        resp = app.make_default_options_response()
        # Example headers (you might customize these)
        resp.headers["Allow"] = "POST, OPTIONS"
        return resp, 200

    # For POST requests
    if request.method != "POST":
        return ("Method Not Allowed", 405)

    # Get JSON payload
    try:
        events = request.get_json()
    except Exception as ex:
        print(f"Error parsing JSON body: {ex}")
        return ("Bad Request - invalid JSON", 400)

    if not events:
        return ("Bad Request - empty body", 400)

    # Event Grid sends the payload as a list of events
    if not isinstance(events, list):
        events = [events]

    # Process each event
    for event in events:
        # Depending on schema, eventType might live under "eventType" or "type"
        event_type = event.get("eventType") or event.get("type")
        data = event.get("data", {})

        # Subscription validation event
        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            # This event has a "validationCode" (and optionally "validationUrl") in data
            validation_code = data.get("validationCode")
            validation_url = data.get("validationUrl")

            if validation_code:
                # According to docs, respond with JSON containing the field "validationResponse"
                resp_body = {"validationResponse": validation_code}
                print("🔐 SubscriptionValidation received, responding with validationResponse")
                return jsonify(resp_body), 200

            # If validationCode not found but validationUrl present, you may do manual validation
            # by doing GET on validationUrl (if your scenario allows). But synchronous code above is preferred.
            if validation_url:
                # Optionally: perform GET to validation_url here (manual handshake)
                try:
                    import requests
                    r = requests.get(validation_url, timeout=10)
                    if r.status_code == 200:
                        return "", 200
                    else:
                        print(f"Validation URL GET failed: status {r.status_code}")
                        return ("Bad Request during manual validation", 400)
                except Exception as ex:
                    print(f"Error during GET validationUrl: {ex}")
                    return ("Bad Request during manual validation", 400)

        # If it’s not a validation event, proceed with normal events
        print(f"🔔 Received Event: {event_type}")
        print(json.dumps(data, indent=2))

        if event_type == "Microsoft.Communication.MessagesReceived":
            # The structure/data may vary depending on the ACS + Event Grid schema
            for message in data.get("messages", []):
                sender = message.get("from")
                text = message.get("content", {}).get("text", {}).get("body", "")

                print(f"📩 Incoming message from {sender}: {text}")

                # Build echo reply
                reply = TextNotificationContent(
                    channel_registration_id=CHANNEL_ID,
                    to=[sender],  # reply to the original sender
                    content=f"You said: {text}"
                )

                response = messaging_client.send(reply)
                receipts = getattr(response, "receipts", None)
                receipt = receipts[0] if receipts and len(receipts) > 0 else None

                if receipt:
                    print(f"✅ Sent reply with messageId={receipt.message_id} to {receipt.to}")
                else:
                    print("⚠️ Failed to get receipt for the reply")

        # You can handle other event types here similarly

    # If we processed non-validation events or validationUrl without code, just return 200
    return "", 200


@app.route("/", methods=["GET"])
def home():
    return "ACS WhatsApp Webhook is running 🚀", 200


if __name__ == "__main__":
    # Production: use HTTPS, proper host/port
    app.run(host="0.0.0.0", port=5000, debug=True)
