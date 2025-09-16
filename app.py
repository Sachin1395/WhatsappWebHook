import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load local environment variables (for local testing only)
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


@app.route("/webhook/messages", methods=["POST"])
def messages_webhook():
    events = request.get_json()

    # Event Grid validation handshake
    if isinstance(events, dict) and events.get("validationCode"):
        return events["validationCode"], 200, {"Content-Type": "text/plain"}

    for event in events:
        event_type = event.get("eventType")
        data = event.get("data", {})

        print(f"🔔 Received Event: {event_type}")
        print(json.dumps(data, indent=2))

        if event_type == "Microsoft.Communication.MessagesReceived":
            for message in data.get("messages", []):
                sender = message.get("from")
                text = message.get("content", {}).get("text", {}).get("body", "")
                print(f"📩 Incoming message from {sender}: {text}")

                reply = TextNotificationContent(
                    channel_registration_id=CHANNEL_ID,
                    to=[sender],
                    content=f"You said: {text}"
                )
                messaging_client.send(reply)

    return "", 200



@app.route("/", methods=["GET"])
def home():
    return "ACS WhatsApp Webhook is running 🚀", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


