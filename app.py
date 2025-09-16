import os
import json
from flask import Flask, request, Response
from dotenv import load_dotenv
from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

# Load local environment variables (for local testing only)
load_dotenv()

app = Flask(__name__)

# Get environment variables (use Azure App Service App Settings in production)
CONNECTION_STRING = os.getenv("COMMUNICATION_SERVICES_CONNECTION_STRING")
CHANNEL_ID = os.getenv("WHATSAPP_CHANNEL_ID")
MY_NUMBER = os.getenv("RECIPIENT_PHONE_NUMBER")

# Create ACS messaging client
messaging_client = NotificationMessagesClient.from_connection_string(CONNECTION_STRING)


@app.route("/webhook/messages", methods=["POST"])
def messages_webhook():
    """
    Handle Event Grid events from ACS (incoming messages, delivery reports, etc.)
    """

    try:
        # Force JSON parsing even if Content-Type is non-standard
        events = request.get_json(force=True)
    except:
        events = {}

    # Event Grid subscription validation handshake
    # Azure sends a single object with validationCode when registering webhook
    if isinstance(events, dict) and "validationCode" in events.get("data", {}):
        validation_code = events["data"]["validationCode"]
        print(f"🔑 Validation request received: {validation_code}")
        # Must return plain text, not JSON
        return Response(validation_code, status=200, mimetype="text/plain")

    # Ensure events is a list for normal processing
    if not isinstance(events, list):
        events = [events]

    for event in events:
        event_type = event.get("eventType")
        data = event.get("data", {})

        print(f"🔔 Received Event: {event_type}")
        print(json.dumps(data, indent=2))

        # Handle incoming WhatsApp messages
        if event_type == "Microsoft.Communication.MessagesReceived":
            for message in data.get("messages", []):
                sender = message.get("from")
                text = message.get("content", {}).get("text", {}).get("body", "")
                print(f"📩 Incoming message from {sender}: {text}")

                # Build echo reply
                reply = TextNotificationContent(
                    channel_registration_id=CHANNEL_ID,
                    to=[sender],  # reply to original sender
                    content=f"You said: {text}"
                )

                try:
                    response = messaging_client.send(reply)
                    receipt = response.receipts[0] if response.receipts else None
                    if receipt:
                        print(f"✅ Sent reply with messageId={receipt.message_id} to {receipt.to}")
                    else:
                        print("⚠️ Failed to send reply")
                except Exception as e:
                    print(f"❌ Error sending reply: {str(e)}")

    return "", 200


@app.route("/", methods=["GET"])
def home():
    return "ACS WhatsApp Webhook is running 🚀", 200


if __name__ == "__main__":
    # Run Flask on Render
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
