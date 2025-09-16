import os
import json
from flask import Flask, request, Response, jsonify
from dotenv import load_dotenv

# Load .env file locally (not needed on Render/Azure since they use App Settings)
load_dotenv()

app = Flask(__name__)

# Azure Communication Services env vars (set in Render/Azure App Settings)
CONNECTION_STRING = os.getenv("COMMUNICATION_SERVICES_CONNECTION_STRING")
CHANNEL_ID = os.getenv("WHATSAPP_CHANNEL_ID")
RECIPIENT_PHONE_NUMBER = os.getenv("RECIPIENT_PHONE_NUMBER")

# Root route (optional health check)
@app.route("/", methods=["GET"])
def home():
    return "✅ Flask Webhook is running!", 200

# Webhook endpoint for Event Grid + WhatsApp messages
@app.route("/webhook/messages", methods=["POST"])
def webhook_messages():
    try:
        events = request.get_json(force=True)
    except Exception as e:
        print(f"⚠️ Error parsing request JSON: {e}")
        return Response("Invalid JSON", status=400)

    # ✅ Handle Event Grid subscription validation
    if isinstance(events, dict) and events.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
        validation_code = events["data"]["validationCode"]
        print(f"🔑 Validation request received: {validation_code}")
        return Response(validation_code, status=200, mimetype="text/plain")

    # ✅ Handle Event Grid array of events
    if isinstance(events, list):
        for event in events:
            if event.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = event["data"]["validationCode"]
                print(f"🔑 Validation request received: {validation_code}")
                return Response(validation_code, status=200, mimetype="text/plain")

            # Normal message received
            if event.get("eventType") == "Microsoft.Communication.ChatMessageReceived":
                message_data = event.get("data", {})
                print(f"📩 Incoming Message: {json.dumps(message_data, indent=2)}")

    # ✅ Respond success for all other cases
    return Response("Event processed", status=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
